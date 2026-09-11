"""Usage tracking for API costs and token consumption."""

from __future__ import annotations

import json as _json
import sqlite3
import time as _time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent.cost_tracker import estimate_cost


@dataclass
class UsageSummary:
    total_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    period: str
    top_providers: list[tuple[str, int]]


class UsageTracker:
    _conn: sqlite3.Connection

    def __init__(self, db_path: Path | None = None) -> None:
        import os
        if db_path is None:
            home = Path(os.environ.get("zeloo_HOME", Path.home() / ".Zeloo"))
            db_path = home / "usage.db"
        self._db_path = Path(db_path)
        self._init_db()

    def _init_db(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS token_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                cached_tokens INTEGER NOT NULL DEFAULT 0,
                cost_usd REAL NOT NULL DEFAULT 0.0,
                session_id TEXT,
                metadata TEXT
            )
        """)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_usage_ts ON token_usage(ts)"
        )
        self._conn.commit()

    def record(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
        session_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        cost = estimate_cost(input_tokens, output_tokens, model)
        now = datetime.now(UTC).timestamp()
        self._conn.execute(
            "INSERT INTO token_usage "
            "(ts, provider, model, input_tokens, output_tokens, cached_tokens, cost_usd, session_id, metadata) "  # noqa: E501
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                now,
                provider,
                model,
                input_tokens,
                output_tokens,
                cached_tokens,
                cost,
                session_id,
                _json.dumps(metadata or {}),
            ),
        )
        self._conn.commit()

    def get_summary(self, period: str = "day") -> UsageSummary:
        seconds_map = {"day": 86400, "week": 604800, "month": 2592000, "all": 0}
        seconds = seconds_map.get(period, 86400)
        now = _time.time()

        if seconds == 0:
            summary_row = self._conn.execute(
                "SELECT COUNT(*), "
                "COALESCE(SUM(input_tokens), 0), "
                "COALESCE(SUM(output_tokens), 0), "
                "COALESCE(SUM(cost_usd), 0.0) "
                "FROM token_usage"
            ).fetchone()
            top_rows = self._conn.execute(
                "SELECT provider, COUNT(*) FROM token_usage "
                "GROUP BY provider ORDER BY COUNT(*) DESC LIMIT 5"
            ).fetchall()
        else:
            since = now - seconds
            summary_row = self._conn.execute(
                "SELECT COUNT(*), "
                "COALESCE(SUM(input_tokens), 0), "
                "COALESCE(SUM(output_tokens), 0), "
                "COALESCE(SUM(cost_usd), 0.0) "
                "FROM token_usage WHERE ts >= ?",
                (since,),
            ).fetchone()
            top_rows = self._conn.execute(
                "SELECT provider, COUNT(*) FROM token_usage "
                "WHERE ts >= ? GROUP BY provider ORDER BY COUNT(*) DESC LIMIT 5",
                (since,),
            ).fetchall()

        row = summary_row or (0, 0, 0, 0.0)
        return UsageSummary(
            total_calls=row[0],
            total_input_tokens=row[1],
            total_output_tokens=row[2],
            total_cost_usd=round(row[3], 6),
            period=period,
            top_providers=[(r[0], r[1]) for r in top_rows],
        )

    def close(self) -> None:
        self._conn.close()


def record_token_usage(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    **kwargs: Any,
) -> None:
    tracker = UsageTracker()
    tracker.record(provider, model, input_tokens, output_tokens, **kwargs)
    tracker.close()
