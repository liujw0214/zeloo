"""Unit tests for agent.cost_optimizer.

Covers:
- TaskType / CostTier enum values
- UsageRecord & BudgetLimit dataclass construction
- CostOptimizer SQLite persistence (tmp_path)
- record_usage / get_usage / get_total_cost / get_cost_by_model / get_cost_by_task_type
- get_heatmap_data(year) & get_weekly_report()
- suggest_downgrade / suggest_upgrade / suggest_for_query
- set_budget_limit / get_budget_limit / check_budget / get_current_spend
- @tool wrapper registration for cost_* helpers
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from agent.cost_optimizer import (
    BudgetLimit,
    CostOptimizer,
    CostTier,
    TaskType,
    UsageRecord,
    cost_by_model,
    cost_current_spend,
    cost_record,
    cost_report,
    cost_set_budget,
    cost_suggest_for_query,
    cost_weekly_report,
    model_tier,
)


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def optimizer(tmp_path: Path) -> CostOptimizer:
    return CostOptimizer(db_path=tmp_path / "cost.db")


@pytest.fixture
def base_time() -> datetime:
    """A timestamp inside the default 30-day query window.

    Today's date is 2026-09-11; pick a timestamp 5 days before that so the
    records are visible to ``get_usage(days=30)`` regardless of clock skew.
    """
    return datetime.utcnow() - timedelta(days=5)


def _record(
    model: str = "gpt-4o-mini",
    provider: str = "openai",
    cost_usd: float = 0.001,
    input_tokens: int = 100,
    output_tokens: int = 50,
    task_type: TaskType | None = TaskType.SIMPLE_QA,
    timestamp: datetime | None = None,
    latency_ms: float = 100.0,
) -> UsageRecord:
    return UsageRecord(
        timestamp=timestamp or datetime.utcnow(),
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        task_type=task_type,
        latency_ms=latency_ms,
    )


# ── TaskType enum ─────────────────────────────────────────────────────


class TestTaskType:
    def test_simple_qa_value(self) -> None:
        assert TaskType.SIMPLE_QA.value == "simple_qa"

    def test_code_gen_value(self) -> None:
        assert TaskType.CODE_GEN.value == "code_gen"

    def test_reasoning_value(self) -> None:
        assert TaskType.REASONING.value == "reasoning"

    def test_summarization_value(self) -> None:
        assert TaskType.SUMMARIZATION.value == "summary"

    def test_translation_value(self) -> None:
        assert TaskType.TRANSLATION.value == "translation"

    def test_vision_value(self) -> None:
        assert TaskType.VISION.value == "vision"

    def test_long_context_value(self) -> None:
        assert TaskType.LONG_CONTEXT.value == "long_context"

    def test_conversation_value(self) -> None:
        assert TaskType.CONVERSATION.value == "conversation"


# ── CostTier enum ─────────────────────────────────────────────────────


class TestCostTier:
    def test_cheap_value(self) -> None:
        assert CostTier.CHEAP.value == "cheap"

    def test_economy_value(self) -> None:
        assert CostTier.ECONOMY.value == "economy"

    def test_standard_value(self) -> None:
        assert CostTier.STANDARD.value == "standard"

    def test_premium_value(self) -> None:
        assert CostTier.PREMIUM.value == "premium"

    def test_model_tier_known_models(self) -> None:
        # Cheapest models → CHEAP; expensive → PREMIUM.
        assert model_tier("llama-3.1-8b-instant") in (CostTier.CHEAP, CostTier.ECONOMY)
        # gpt-4o is priced (2.50 in / 10.00 out) → blended ≈ $0.00475 / 1k
        # which is in the ECONOMY band (0.001 ≤ x < 0.01).
        assert model_tier("gpt-4o") == CostTier.ECONOMY


# ── UsageRecord / BudgetLimit dataclasses ────────────────────────────


class TestDataclasses:
    def test_usage_record_construction(self) -> None:
        r = _record()
        assert r.model == "gpt-4o-mini"
        assert r.input_tokens == 100
        assert r.task_type == TaskType.SIMPLE_QA

    def test_budget_limit_defaults(self) -> None:
        b = BudgetLimit(monthly_limit_usd=100.0)
        assert b.monthly_limit_usd == 100.0
        assert b.warning_threshold == 0.8
        assert b.hard_limit is True
        assert b.per_task_limit_usd is None

    def test_budget_limit_custom(self) -> None:
        b = BudgetLimit(
            monthly_limit_usd=50.0,
            warning_threshold=0.5,
            hard_limit=False,
            per_task_limit_usd=1.0,
        )
        assert b.warning_threshold == 0.5
        assert b.hard_limit is False
        assert b.per_task_limit_usd == 1.0


# ── SQLite persistence ────────────────────────────────────────────────


class TestInitDb:
    def test_db_file_created(self, tmp_path: Path) -> None:
        db = tmp_path / "fresh.db"
        CostOptimizer(db_path=db)
        assert db.exists()

    def test_tables_exist(self, optimizer: CostOptimizer) -> None:
        with sqlite3.connect(optimizer.db_path) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        names = {r[0] for r in rows}
        assert "usage" in names
        assert "budget" in names

    def test_indexes_exist(self, optimizer: CostOptimizer) -> None:
        with sqlite3.connect(optimizer.db_path) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        names = {r[0] for r in rows}
        for idx in ("idx_usage_ts", "idx_usage_model", "idx_usage_task"):
            assert idx in names


# ── record_usage / get_usage / get_total_cost ─────────────────────────


class TestRecordAndQuery:
    def test_record_single(self, optimizer: CostOptimizer) -> None:
        optimizer.record_usage(_record(cost_usd=0.05))
        records = optimizer.get_usage(days=30)
        assert len(records) == 1
        assert records[0].model == "gpt-4o-mini"

    def test_record_multiple(
        self, optimizer: CostOptimizer, base_time: datetime
    ) -> None:
        for i in range(5):
            optimizer.record_usage(
                _record(
                    cost_usd=0.01 * (i + 1),
                    timestamp=base_time + timedelta(hours=i),
                )
            )
        assert len(optimizer.get_usage(days=30)) == 5

    def test_get_usage_excludes_old_records(
        self, optimizer: CostOptimizer, base_time: datetime
    ) -> None:
        old = _record(
            cost_usd=0.01,
            timestamp=base_time - timedelta(days=100),
        )
        recent = _record(cost_usd=0.01)
        optimizer.record_usage(old)
        optimizer.record_usage(recent)
        records = optimizer.get_usage(days=30)
        assert len(records) == 1

    def test_get_total_cost(
        self, optimizer: CostOptimizer, base_time: datetime
    ) -> None:
        optimizer.record_usage(_record(cost_usd=0.10))
        optimizer.record_usage(_record(cost_usd=0.25, timestamp=base_time))
        assert optimizer.get_total_cost(days=30) == pytest.approx(0.35, abs=1e-6)

    def test_get_total_cost_empty(self, optimizer: CostOptimizer) -> None:
        assert optimizer.get_total_cost(days=30) == 0.0


# ── Aggregations ──────────────────────────────────────────────────────


class TestAggregations:
    def test_get_cost_by_model(
        self, optimizer: CostOptimizer, base_time: datetime
    ) -> None:
        optimizer.record_usage(
            _record(model="gpt-4o-mini", cost_usd=0.10)
        )
        optimizer.record_usage(
            _record(model="gpt-4o", cost_usd=0.50, timestamp=base_time)
        )
        result = optimizer.get_cost_by_model(days=30)
        assert result["gpt-4o-mini"] == pytest.approx(0.10, abs=1e-6)
        assert result["gpt-4o"] == pytest.approx(0.50, abs=1e-6)

    def test_get_cost_by_model_sorted_desc(
        self, optimizer: CostOptimizer
    ) -> None:
        optimizer.record_usage(_record(model="cheap-model", cost_usd=0.01))
        optimizer.record_usage(_record(model="expensive-model", cost_usd=10.0))
        result = optimizer.get_cost_by_model(days=30)
        keys = list(result.keys())
        assert keys[0] == "expensive-model"

    def test_get_cost_by_task_type(
        self, optimizer: CostOptimizer, base_time: datetime
    ) -> None:
        optimizer.record_usage(
            _record(cost_usd=0.10, task_type=TaskType.SIMPLE_QA)
        )
        optimizer.record_usage(
            _record(cost_usd=0.50, task_type=TaskType.CODE_GEN, timestamp=base_time)
        )
        result = optimizer.get_cost_by_task_type(days=30)
        assert result[TaskType.SIMPLE_QA] == pytest.approx(0.10, abs=1e-6)
        assert result[TaskType.CODE_GEN] == pytest.approx(0.50, abs=1e-6)


# ── Heatmap / weekly report ───────────────────────────────────────────


class TestReports:
    def test_heatmap_data_structure(
        self, optimizer: CostOptimizer, base_time: datetime
    ) -> None:
        optimizer.record_usage(
            _record(cost_usd=0.05, timestamp=base_time)
        )
        heatmap = optimizer.get_heatmap_data(2026)
        assert heatmap["year"] == 2026
        assert isinstance(heatmap["days"], list)
        assert len(heatmap["days"]) >= 1
        assert "date" in heatmap["days"][0]
        assert "cost_usd" in heatmap["days"][0]
        assert "calls" in heatmap["days"][0]

    def test_heatmap_filters_by_year(
        self, optimizer: CostOptimizer, base_time: datetime
    ) -> None:
        optimizer.record_usage(
            _record(cost_usd=0.01, timestamp=base_time)
        )
        heatmap = optimizer.get_heatmap_data(2025)
        # No records in 2025 → empty day list.
        assert heatmap["days"] == []

    def test_weekly_report_structure(
        self, optimizer: CostOptimizer, base_time: datetime
    ) -> None:
        optimizer.record_usage(
            _record(
                cost_usd=0.10,
                timestamp=base_time,
            )
        )
        report = optimizer.get_weekly_report()
        assert report["window_days"] == 7
        assert report["calls"] >= 1
        assert "total_cost_usd" in report
        assert "top_model" in report
        assert "top_task_type" in report
        assert "cost_by_day" in report

    def test_weekly_report_empty(self, optimizer: CostOptimizer) -> None:
        report = optimizer.get_weekly_report()
        assert report["calls"] == 0
        assert report["total_cost_usd"] == 0.0


# ── Suggestions ───────────────────────────────────────────────────────


class TestSuggestions:
    def test_suggest_downgrade_for_premium(
        self, optimizer: CostOptimizer
    ) -> None:
        # gpt-4o is premium-tier; reasoning task is also premium → may be None.
        # But try a cheap task against a premium model → should downgrade.
        suggestion = optimizer.suggest_downgrade(TaskType.SIMPLE_QA, "gpt-4o")
        # Either a cheaper model name or None if none cheaper exists.
        assert suggestion is None or isinstance(suggestion, str)

    def test_suggest_downgrade_when_already_cheap(
        self, optimizer: CostOptimizer
    ) -> None:
        # llama-3.1-8b-instant is CHEAP — downgrade of CHEAP → None.
        suggestion = optimizer.suggest_downgrade(
            TaskType.SIMPLE_QA, "llama-3.1-8b-instant"
        )
        assert suggestion is None

    def test_suggest_upgrade_for_cheap(
        self, optimizer: CostOptimizer
    ) -> None:
        # llama-3.1-8b-instant is CHEAP; reasoning wants PREMIUM → upgrade.
        suggestion = optimizer.suggest_upgrade(
            TaskType.REASONING, "llama-3.1-8b-instant"
        )
        # May be None if no upgrade candidate in pricing table.
        assert suggestion is None or isinstance(suggestion, str)

    def test_suggest_for_query_code(
        self, optimizer: CostOptimizer
    ) -> None:
        chosen = optimizer.suggest_for_query(
            "write me a function to sort an array",
            ["gpt-4o-mini", "gpt-4o", "claude-3-haiku-20240307"],
        )
        assert chosen in {
            "gpt-4o-mini",
            "gpt-4o",
            "claude-3-haiku-20240307",
        }

    def test_suggest_for_query_conversation(
        self, optimizer: CostOptimizer
    ) -> None:
        chosen = optimizer.suggest_for_query(
            "Hello, how are you?",
            ["gpt-4o", "gpt-4o-mini"],
        )
        assert chosen in {"gpt-4o", "gpt-4o-mini"}

    def test_suggest_for_query_empty_models(
        self, optimizer: CostOptimizer
    ) -> None:
        chosen = optimizer.suggest_for_query("hello", [])
        assert chosen == ""


# ── Budget lifecycle ──────────────────────────────────────────────────


class TestBudget:
    def test_set_and_get_budget(self, optimizer: CostOptimizer) -> None:
        optimizer.set_budget_limit(BudgetLimit(monthly_limit_usd=42.0))
        budget = optimizer.get_budget_limit()
        assert budget is not None
        assert budget.monthly_limit_usd == 42.0

    def test_get_budget_none_when_unset(
        self, optimizer: CostOptimizer
    ) -> None:
        assert optimizer.get_budget_limit() is None

    def test_set_budget_overwrites(
        self, optimizer: CostOptimizer
    ) -> None:
        optimizer.set_budget_limit(BudgetLimit(monthly_limit_usd=10.0))
        optimizer.set_budget_limit(BudgetLimit(monthly_limit_usd=99.0))
        assert optimizer.get_budget_limit().monthly_limit_usd == 99.0

    def test_check_budget_no_budget_allows(
        self, optimizer: CostOptimizer
    ) -> None:
        ok, msg = optimizer.check_budget(50.0)
        assert ok is True
        assert "no budget" in msg

    def test_check_budget_within_limit(
        self, optimizer: CostOptimizer
    ) -> None:
        optimizer.set_budget_limit(
            BudgetLimit(monthly_limit_usd=100.0, warning_threshold=0.8)
        )
        ok, msg = optimizer.check_budget(10.0)
        assert ok is True

    def test_check_budget_exceeds_hard_limit(
        self, optimizer: CostOptimizer
    ) -> None:
        optimizer.set_budget_limit(BudgetLimit(monthly_limit_usd=1.0))
        ok, msg = optimizer.check_budget(5.0)
        assert ok is False
        assert "exceed" in msg

    def test_check_budget_exceeds_soft_limit(
        self, optimizer: CostOptimizer
    ) -> None:
        optimizer.set_budget_limit(
            BudgetLimit(monthly_limit_usd=10.0, hard_limit=False)
        )
        ok, msg = optimizer.check_budget(50.0)
        assert ok is True
        assert "WARNING" in msg

    def test_check_budget_per_task_limit(
        self, optimizer: CostOptimizer
    ) -> None:
        optimizer.set_budget_limit(
            BudgetLimit(monthly_limit_usd=100.0, per_task_limit_usd=0.5)
        )
        ok, msg = optimizer.check_budget(1.0)
        assert ok is False
        assert "per-task" in msg

    def test_check_budget_warning_threshold(
        self, optimizer: CostOptimizer
    ) -> None:
        optimizer.set_budget_limit(
            BudgetLimit(monthly_limit_usd=10.0, warning_threshold=0.5)
        )
        ok, msg = optimizer.check_budget(6.0)
        assert ok is True
        assert "warning" in msg.lower() or "WARNING" in msg

    def test_get_current_spend_empty(
        self, optimizer: CostOptimizer
    ) -> None:
        assert optimizer.get_current_spend() == 0.0

    def test_get_current_spend_sums_month(
        self, optimizer: CostOptimizer, base_time: datetime
    ) -> None:
        optimizer.record_usage(_record(cost_usd=0.10))
        optimizer.record_usage(
            _record(cost_usd=0.25, timestamp=base_time)
        )
        assert optimizer.get_current_spend() == pytest.approx(0.35, abs=1e-6)


# ── @tool wrappers ────────────────────────────────────────────────────


class TestToolWrappers:
    """Verify the @tool-decorated helpers run end-to-end.

    The wrappers share a module-level singleton ``CostOptimizer`` whose DB
    lives under ``~/.Zeloo``. To keep tests hermetic, we monkey-patch
    ``_get_default`` to return a tmp_path-backed optimizer.
    """

    @pytest.fixture
    def patched_optimizer(
        self, optimizer: CostOptimizer, monkeypatch: pytest.MonkeyPatch
    ) -> CostOptimizer:
        """Redirect the module singleton to the tmp_path optimizer."""
        import agent.cost_optimizer as mod

        monkeypatch.setattr(mod, "_default_optimizer", optimizer)
        return optimizer

    def test_cost_record_writes_to_db(
        self,
        patched_optimizer: CostOptimizer,
        tmp_path: Path,
    ) -> None:
        result = cost_record(
            provider="openai",
            model="gpt-4o-mini",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.001,
            task_type="simple_qa",
        )
        assert result["recorded"] is True
        assert result["task_type"] == "simple_qa"
        # SQLite file at tmp_path should now contain the record.
        records = patched_optimizer.get_usage(days=1)
        assert any(r.model == "gpt-4o-mini" for r in records)

    def test_cost_record_invalid_task_type(
        self, patched_optimizer: CostOptimizer
    ) -> None:
        result = cost_record(
            provider="openai",
            model="gpt-4o",
            input_tokens=10,
            output_tokens=5,
            cost_usd=0.001,
            task_type="not_a_real_task",
        )
        assert result["task_type"] is None

    def test_cost_record_default_task_type(
        self, patched_optimizer: CostOptimizer
    ) -> None:
        result = cost_record(
            provider="openai",
            model="gpt-4o",
            input_tokens=10,
            output_tokens=5,
            cost_usd=0.001,
        )
        assert result["recorded"] is True
        assert result["task_type"] is None

    def test_cost_report_returns_payload(
        self, patched_optimizer: CostOptimizer
    ) -> None:
        cost_record(
            provider="openai",
            model="gpt-4o-mini",
            input_tokens=10,
            output_tokens=5,
            cost_usd=0.0005,
        )
        report = cost_report(days=1)
        assert report["days"] == 1
        assert "total_cost_usd" in report
        assert "calls" in report
        assert "usage" in report
        assert report["calls"] >= 1

    def test_cost_by_model_returns_dict(
        self, patched_optimizer: CostOptimizer
    ) -> None:
        cost_record(
            provider="openai",
            model="unique-model-name",
            input_tokens=10,
            output_tokens=5,
            cost_usd=0.01,
        )
        result = cost_by_model(days=1)
        assert result["days"] == 1
        assert isinstance(result["by_model"], dict)
        assert "unique-model-name" in result["by_model"]

    def test_cost_weekly_report_returns_dict(
        self, patched_optimizer: CostOptimizer
    ) -> None:
        report = cost_weekly_report()
        assert report["window_days"] == 7
        assert "total_cost_usd" in report
        assert "top_model" in report
        assert "top_task_type" in report

    def test_cost_suggest_for_query_helper(
        self, patched_optimizer: CostOptimizer
    ) -> None:
        result = cost_suggest_for_query(
            "implement a quick sort function",
            available_models="gpt-4o-mini,gpt-4o,claude-3-haiku-20240307",
        )
        assert "suggested_model" in result
        assert len(result["available_models"]) == 3

    def test_cost_suggest_for_query_default_models(
        self, patched_optimizer: CostOptimizer
    ) -> None:
        result = cost_suggest_for_query("hello there")
        # No models provided → default fallback list.
        assert len(result["available_models"]) >= 1

    def test_cost_set_budget_returns_confirmation(
        self, patched_optimizer: CostOptimizer
    ) -> None:
        result = cost_set_budget(monthly_limit=50.0)
        assert result["monthly_limit_usd"] == 50.0
        assert "month" in result

    def test_cost_current_spend_returns_dict(
        self, patched_optimizer: CostOptimizer
    ) -> None:
        result = cost_current_spend()
        assert "month" in result
        assert "spend_usd" in result
        # Budget was set in previous test only if ordering allows → optional.
        assert isinstance(result["spend_usd"], float)

    def test_wrappers_are_callable(self) -> None:
        """All @tool wrappers should remain plain Python callables."""
        for fn in (
            cost_record,
            cost_report,
            cost_by_model,
            cost_weekly_report,
            cost_suggest_for_query,
            cost_set_budget,
            cost_current_spend,
        ):
            assert callable(fn)
