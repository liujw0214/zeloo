"""Cost optimizer — record, analyse, and budget LLM usage.

Persistent storage uses SQLite under ``~/.Zeloo/cost.db``. The module
also exposes ``@tool``-decorated helper functions for direct agent use.

Style mirrors ``cost_tracker.py`` (module-level logger, dataclass +
``Enum``).
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

from agent.cost_tracker import get_model_price
from agent.zeloo_constants import get_zeloo_home

try:
    from tools.base import tool as _tool_decorator  # type: ignore
except Exception:  # pragma: no cover
    _tool_decorator = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)


class TaskType(Enum):
    SIMPLE_QA = "simple_qa"
    CODE_GEN = "code_gen"
    REASONING = "reasoning"
    SUMMARIZATION = "summary"
    TRANSLATION = "translation"
    VISION = "vision"
    LONG_CONTEXT = "long_context"
    CONVERSATION = "conversation"


class CostTier(Enum):
    CHEAP = "cheap"          # < $0.001 / 1k tokens
    ECONOMY = "economy"      # $0.001-$0.01 / 1k
    STANDARD = "standard"    # $0.01-$0.05 / 1k
    PREMIUM = "premium"      # > $0.05 / 1k


@dataclass
class UsageRecord:
    timestamp: datetime
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    task_type: TaskType | None = None
    latency_ms: float = 0.0


@dataclass
class BudgetLimit:
    monthly_limit_usd: float
    warning_threshold: float = 0.8
    hard_limit: bool = True
    per_task_limit_usd: float | None = None


# Recommended target tier per task type.
_TASK_TIER_AFFINITY: dict[TaskType, CostTier] = {
    TaskType.REASONING: CostTier.PREMIUM,
    TaskType.LONG_CONTEXT: CostTier.STANDARD,
    TaskType.SIMPLE_QA: CostTier.CHEAP,
    TaskType.TRANSLATION: CostTier.ECONOMY,
    TaskType.SUMMARIZATION: CostTier.ECONOMY,
    TaskType.CONVERSATION: CostTier.ECONOMY,
    TaskType.CODE_GEN: CostTier.STANDARD,
    TaskType.VISION: CostTier.STANDARD,
}

_TIER_RANK = {CostTier.CHEAP: 0, CostTier.ECONOMY: 1, CostTier.STANDARD: 2, CostTier.PREMIUM: 3}


def model_tier(model: str) -> CostTier:
    """Return the :class:`CostTier` of *model* based on its listed price."""
    price_in, price_out = get_model_price(model)
    blended = (price_in * 0.7 + price_out * 0.3) / 1000.0  # USD / 1k tokens
    if blended < 0.001:
        return CostTier.CHEAP
    if blended < 0.01:
        return CostTier.ECONOMY
    if blended < 0.05:
        return CostTier.STANDARD
    return CostTier.PREMIUM


def _month_key(now: datetime | None = None) -> str:
    now = now or datetime.utcnow()
    return f"{now.year:04d}-{now.month:02d}"


class CostOptimizer:
    """Record and analyse LLM costs with SQLite persistence.

    Args:
        db_path: SQLite file path. ``None`` → ``~/.Zeloo/cost.db``.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else get_zeloo_home() / "cost.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._budget: BudgetLimit | None = None
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL,
                    cost_usd REAL NOT NULL,
                    task_type TEXT,
                    latency_ms REAL DEFAULT 0.0
                );
                CREATE INDEX IF NOT EXISTS idx_usage_ts ON usage(ts);
                CREATE INDEX IF NOT EXISTS idx_usage_model ON usage(model);
                CREATE INDEX IF NOT EXISTS idx_usage_task ON usage(task_type);
                CREATE TABLE IF NOT EXISTS budget (
                    month TEXT PRIMARY KEY,
                    monthly_limit_usd REAL NOT NULL,
                    warning_threshold REAL NOT NULL,
                    hard_limit INTEGER NOT NULL,
                    per_task_limit_usd REAL
                );
                """
            )

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    # ── Recording ────────────────────────────────────────────────

    def record_usage(self, record: UsageRecord) -> None:
        """Persist a single :class:`UsageRecord`."""
        with self._lock, self._conn() as conn:
            conn.execute(
                """
                INSERT INTO usage (ts, provider, model, input_tokens,
                                   output_tokens, cost_usd, task_type, latency_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.timestamp.isoformat(),
                    record.provider,
                    record.model,
                    int(record.input_tokens),
                    int(record.output_tokens),
                    float(record.cost_usd),
                    record.task_type.value if record.task_type else None,
                    float(record.latency_ms),
                ),
            )
            conn.commit()

    # ── Querying ─────────────────────────────────────────────────

    def get_usage(self, days: int = 30) -> list[UsageRecord]:
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT ts, provider, model, input_tokens, output_tokens,
                       cost_usd, task_type, latency_ms
                FROM usage WHERE ts >= ? ORDER BY ts ASC
                """,
                (cutoff,),
            ).fetchall()
        return [
            UsageRecord(
                timestamp=datetime.fromisoformat(ts),
                provider=provider,
                model=model,
                input_tokens=int(in_tok),
                output_tokens=int(out_tok),
                cost_usd=float(cost),
                task_type=TaskType(task_type) if task_type else None,
                latency_ms=float(latency or 0.0),
            )
            for ts, provider, model, in_tok, out_tok, cost, task_type, latency in rows
        ]

    def get_total_cost(self, days: int = 30) -> float:
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0.0) FROM usage WHERE ts >= ?",
                (cutoff,),
            ).fetchone()
        return float(row[0] or 0.0)

    def get_cost_by_model(self, days: int = 30) -> dict[str, float]:
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT model, COALESCE(SUM(cost_usd), 0.0) AS total
                FROM usage WHERE ts >= ?
                GROUP BY model ORDER BY total DESC
                """,
                (cutoff,),
            ).fetchall()
        return {model: float(total) for model, total in rows}

    def get_cost_by_task_type(self, days: int = 30) -> dict[TaskType, float]:
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        result: dict[TaskType, float] = defaultdict(float)
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT task_type, COALESCE(SUM(cost_usd), 0.0) AS total
                FROM usage WHERE ts >= ?
                GROUP BY task_type
                """,
                (cutoff,),
            ).fetchall()
        for task_type, total in rows:
            try:
                result[TaskType(task_type)] = float(total)
            except ValueError:
                continue
        return dict(result)

    def get_heatmap_data(self, year: int) -> dict[str, Any]:
        """Return per-day cost + call-count for the calendar *year*."""
        start = datetime(year, 1, 1)
        end = datetime(year + 1, 1, 1)
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT substr(ts, 1, 10) AS day,
                       COALESCE(SUM(cost_usd), 0.0) AS cost,
                       COUNT(*) AS calls
                FROM usage WHERE ts >= ? AND ts < ?
                GROUP BY day ORDER BY day
                """,
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        return {
            "year": year,
            "days": [
                {"date": day, "cost_usd": float(cost), "calls": int(calls)}
                for day, cost, calls in rows
            ],
        }

    def get_weekly_report(self) -> dict[str, Any]:
        """Rolling 7-day summary: spend, top models, top tasks, per-day split."""
        records = self.get_usage(days=7)
        by_model: dict[str, float] = defaultdict(float)
        by_task: dict[str, float] = defaultdict(float)
        by_day: dict[str, float] = defaultdict(float)
        for r in records:
            by_model[r.model] += r.cost_usd
            if r.task_type:
                by_task[r.task_type.value] += r.cost_usd
            by_day[r.timestamp.date().isoformat()] += r.cost_usd
        top_model = max(by_model.items(), key=lambda kv: kv[1], default=("", 0.0))
        top_task = max(by_task.items(), key=lambda kv: kv[1], default=("", 0.0))
        return {
            "window_days": 7,
            "total_cost_usd": round(sum(by_model.values()), 6),
            "calls": len(records),
            "top_model": {"name": top_model[0], "cost_usd": round(top_model[1], 6)},
            "top_task_type": {"name": top_task[0], "cost_usd": round(top_task[1], 6)},
            "cost_by_model": {k: round(v, 6) for k, v in by_model.items()},
            "cost_by_task_type": {k: round(v, 6) for k, v in by_task.items()},
            "cost_by_day": {k: round(v, 6) for k, v in by_day.items()},
        }

    # ── Suggestions ──────────────────────────────────────────────

    def suggest_downgrade(self, task_type: TaskType, current_model: str) -> str | None:
        """Suggest a cheaper model in a lower tier. ``None`` if already optimal."""
        current_rank = _TIER_RANK[model_tier(current_model)]
        target_rank = _TIER_RANK[_TASK_TIER_AFFINITY.get(task_type, CostTier.ECONOMY)]
        if current_rank <= target_rank:
            return None
        from agent.cost_tracker import _MODEL_PRICING
        candidates = [
            (pin + pout, name)
            for name, (pin, pout) in _MODEL_PRICING.items()
            if name != current_model and _TIER_RANK[model_tier(name)] < current_rank
        ]
        return min(candidates)[1] if candidates else None

    def suggest_upgrade(self, task_type: TaskType, current_model: str) -> str | None:
        """Suggest a more capable model for *task_type*, ``None`` if already fine."""
        current_rank = _TIER_RANK[model_tier(current_model)]
        target_rank = _TIER_RANK[_TASK_TIER_AFFINITY.get(task_type, CostTier.STANDARD)]
        if current_rank >= target_rank:
            return None
        from agent.cost_tracker import _MODEL_PRICING
        candidates = [
            (pin + pout, name)
            for name, (pin, pout) in _MODEL_PRICING.items()
            if name != current_model
            and current_rank < _TIER_RANK[model_tier(name)] <= target_rank
        ]
        return min(candidates)[1] if candidates else None

    def suggest_for_query(self, query: str, available_models: list[str]) -> str:
        """Heuristically pick a model from *available_models* for *query*."""
        q = (query or "").lower()
        if any(k in q for k in ("code", "implement", "function", "代码", "实现")):
            task = TaskType.CODE_GEN
        elif any(k in q for k in ("why", "explain", "analyse", "reason", "为什么", "分析")):
            task = TaskType.REASONING
        elif any(k in q for k in ("hello", "hi", "thanks", "你好", "谢谢")) and len(q) < 40:
            task = TaskType.SIMPLE_QA
        else:
            task = TaskType.CONVERSATION
        target_rank = _TIER_RANK[_TASK_TIER_AFFINITY.get(task, CostTier.ECONOMY)]
        ranked = sorted(
            available_models,
            key=lambda n: abs(_TIER_RANK[model_tier(n)] - target_rank),
        )
        return ranked[0] if ranked else ""

    # ── Budgeting ────────────────────────────────────────────────

    def set_budget_limit(self, limit: BudgetLimit) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(
                """
                INSERT INTO budget (month, monthly_limit_usd,
                                    warning_threshold, hard_limit, per_task_limit_usd)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(month) DO UPDATE SET
                    monthly_limit_usd=excluded.monthly_limit_usd,
                    warning_threshold=excluded.warning_threshold,
                    hard_limit=excluded.hard_limit,
                    per_task_limit_usd=excluded.per_task_limit_usd
                """,
                (
                    _month_key(),
                    float(limit.monthly_limit_usd),
                    float(limit.warning_threshold),
                    int(limit.hard_limit),
                    limit.per_task_limit_usd,
                ),
            )
            conn.commit()
        self._budget = limit

    def get_budget_limit(self) -> BudgetLimit | None:
        if self._budget is not None:
            return self._budget
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT monthly_limit_usd, warning_threshold, hard_limit,
                       per_task_limit_usd FROM budget WHERE month = ?
                """,
                (_month_key(),),
            ).fetchone()
        if not row:
            return None
        self._budget = BudgetLimit(
            monthly_limit_usd=float(row[0]),
            warning_threshold=float(row[1]),
            hard_limit=bool(row[2]),
            per_task_limit_usd=float(row[3]) if row[3] is not None else None,
        )
        return self._budget

    def check_budget(self, estimated_cost: float) -> tuple[bool, str]:
        """Check whether *estimated_cost* can be spent under the active budget."""
        budget = self.get_budget_limit()
        if budget is None:
            return True, "no budget configured"
        spend = self.get_current_spend()
        projected = spend + estimated_cost
        if budget.per_task_limit_usd is not None and estimated_cost > budget.per_task_limit_usd:
            return False, (
                f"per-task cost ${estimated_cost:.4f} exceeds "
                f"per_task_limit_usd ${budget.per_task_limit_usd:.4f}"
            )
        if projected >= budget.monthly_limit_usd:
            if budget.hard_limit:
                return False, (
                    f"projected monthly spend ${projected:.4f} would exceed "
                    f"limit ${budget.monthly_limit_usd:.4f}"
                )
            return True, (
                f"WARNING: projected spend ${projected:.4f} exceeds monthly "
                f"limit ${budget.monthly_limit_usd:.4f} (hard_limit disabled)"
            )
        warning_at = budget.monthly_limit_usd * budget.warning_threshold
        if projected >= warning_at:
            return True, (
                f"WARNING: projected spend ${projected:.4f} crossed "
                f"warning threshold ${warning_at:.4f}"
            )
        return True, f"ok (projected ${projected:.4f} / ${budget.monthly_limit_usd:.4f})"

    def get_current_spend(self, month: str | None = None) -> float:
        key = month or _month_key()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0.0) FROM usage WHERE substr(ts, 1, 7) = ?",
                (key,),
            ).fetchone()
        return float(row[0] or 0.0)


# ──────────────────────────────────────────────────────────────────────
# @tool wrappers
# ──────────────────────────────────────────────────────────────────────

_default_optimizer: CostOptimizer | None = None
_default_lock = threading.Lock()


def _get_default() -> CostOptimizer:
    """Lazy-initialised module-level singleton."""
    global _default_optimizer
    if _default_optimizer is None:
        with _default_lock:
            if _default_optimizer is None:
                _default_optimizer = CostOptimizer()
    return _default_optimizer


def _tool(name: str | None = None, description: str = ""):
    """Use ``tools.base.tool`` when available; fall back to identity."""
    if _tool_decorator is None:
        def _identity(func):
            func.__tool_name__ = name or func.__name__
            return func
        return _identity
    return _tool_decorator(name=name, description=description, toolset="cost")


@_tool(name="cost_record", description="Record an LLM usage event")
def cost_record(provider: str, model: str, input_tokens: int, output_tokens: int,
                cost_usd: float, task_type: str | None = None) -> dict:
    """Record a single LLM call for cost tracking."""
    tt: TaskType | None = None
    if task_type:
        try:
            tt = TaskType(task_type)
        except ValueError:
            tt = None
    _get_default().record_usage(UsageRecord(
        timestamp=datetime.utcnow(), provider=provider, model=model,
        input_tokens=int(input_tokens), output_tokens=int(output_tokens),
        cost_usd=float(cost_usd), task_type=tt,
    ))
    return {"recorded": True, "task_type": tt.value if tt else None}


@_tool(name="cost_report", description="Generate a usage report for the last N days")
def cost_report(days: int = 30) -> dict:
    """Return total cost + per-call record for the last *days* days."""
    opt = _get_default()
    records = opt.get_usage(days=days)
    return {
        "days": days,
        "total_cost_usd": round(opt.get_total_cost(days=days), 6),
        "calls": len(records),
        "usage": [
            {
                "timestamp": r.timestamp.isoformat(), "provider": r.provider,
                "model": r.model, "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens, "cost_usd": round(r.cost_usd, 6),
                "task_type": r.task_type.value if r.task_type else None,
                "latency_ms": r.latency_ms,
            }
            for r in records
        ],
    }


@_tool(name="cost_by_model", description="Break down spend by model")
def cost_by_model(days: int = 30) -> dict:
    """Return ``{model: cost_usd}`` for the last *days* days."""
    return {"days": days, "by_model": {
        k: round(v, 6)
        for k, v in _get_default().get_cost_by_model(days=days).items()
    }}


@_tool(name="cost_weekly_report", description="7-day rolling cost report")
def cost_weekly_report() -> dict:
    """Return the rolling 7-day cost summary."""
    return _get_default().get_weekly_report()


@_tool(name="cost_suggest_for_query",
       description="Suggest a suitable model from a given list for a query")
def cost_suggest_for_query(query: str, available_models: str | None = None) -> dict:
    """Pick a model for *query* from a comma-separated *available_models* list."""
    models = [m.strip() for m in (available_models or "").split(",") if m.strip()] \
        or ["gpt-4o-mini", "gpt-4o", "claude-3-haiku-20240307"]
    return {"suggested_model": _get_default().suggest_for_query(query, models),
            "available_models": models}


@_tool(name="cost_set_budget", description="Set the monthly cost budget")
def cost_set_budget(monthly_limit: float) -> dict:
    """Persist a monthly budget and return confirmation."""
    limit = BudgetLimit(monthly_limit_usd=float(monthly_limit))
    _get_default().set_budget_limit(limit)
    return {"monthly_limit_usd": limit.monthly_limit_usd, "month": _month_key()}


@_tool(name="cost_current_spend", description="Return current-month spend")
def cost_current_spend() -> dict:
    """Return current-month spend and the active budget (if any)."""
    opt = _get_default()
    spend = opt.get_current_spend()
    budget = opt.get_budget_limit()
    return {
        "month": _month_key(),
        "spend_usd": round(spend, 6),
        "budget_usd": budget.monthly_limit_usd if budget else None,
        "remaining_usd": round(budget.monthly_limit_usd - spend, 6) if budget else None,
    }


__all__ = [
    "TaskType", "CostTier", "UsageRecord", "BudgetLimit", "CostOptimizer",
    "cost_record", "cost_report", "cost_by_model", "cost_weekly_report",
    "cost_suggest_for_query", "cost_set_budget", "cost_current_spend",
]
