"""Unit tests for agent.hierarchical_planner.

Covers:
- HierarchicalPlanner default init
- plan_offline() assembling SubPlan and TaskSpec without LLM
- plan() falling back to offline when llm_call is missing
- execute_subgoal() with registered tool executors
- execute_subgoal() dependency ordering
- execute_subgoal() skipping when no executor registered
- get_progress() ratios
- TaskResult.succeeded property
- SubPlan / TaskSpec / HierarchicalPlan dataclasses
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.hierarchical_planner import (
    HierarchicalPlan,
    HierarchicalPlanner,
    SubPlan,
    TaskResult,
    TaskSpec,
)


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def planner(tmp_path: Path) -> HierarchicalPlanner:
    return HierarchicalPlanner(plans_dir=tmp_path / "plans")


@pytest.fixture
def sample_subgoals() -> list[dict]:
    return [
        {
            "title": "Collect data",
            "description": "Gather inputs",
            "tasks": [
                {"description": "fetch input", "tool": "fetch"},
                {"description": "validate input", "tool": "validate", "depends_on": ["task-1"]},
            ],
        },
        {
            "title": "Produce output",
            "description": "Generate result",
            "tasks": [{"description": "write file", "tool": "writer"}],
        },
    ]


# ── Init ──────────────────────────────────────────────────────────────


class TestInit:
    def test_default_init(self, tmp_path: Path) -> None:
        planner = HierarchicalPlanner(plans_dir=tmp_path / "p")
        assert planner.llm_provider == "anthropic"
        assert planner.llm_model == "claude-3-5-sonnet"
        assert planner.llm_call is None
        assert planner.plans_dir.exists()


# ── plan_offline ──────────────────────────────────────────────────────


class TestPlanOffline:
    def test_builds_plan_from_dict(self, planner: HierarchicalPlanner, sample_subgoals: list[dict]) -> None:
        plan = planner.plan_offline("ship feature", sample_subgoals)
        assert isinstance(plan, HierarchicalPlan)
        assert plan.goal == "ship feature"
        assert len(plan.subgoals) == 2
        assert plan.subgoals[0].title == "Collect data"
        assert len(plan.subgoals[0].tasks) == 2

    def test_persists_plan_to_disk(self, planner: HierarchicalPlanner, sample_subgoals: list[dict]) -> None:
        plan = planner.plan_offline("goal", sample_subgoals)
        persisted = list(planner.plans_dir.glob("*.json"))
        assert len(persisted) == 1
        assert persisted[0].stem == plan.plan_id

    def test_empty_subgoals(self, planner: HierarchicalPlanner) -> None:
        plan = planner.plan_offline("noop", [])
        assert plan.subgoals == []

    def test_metadata_offline(self, planner: HierarchicalPlanner) -> None:
        plan = planner.plan_offline("g", [{"title": "x", "description": "y", "tasks": []}])
        assert plan.metadata.get("source") == "offline"

    def test_subplan_default_status(self, planner: HierarchicalPlanner, sample_subgoals: list[dict]) -> None:
        plan = planner.plan_offline("g", sample_subgoals)
        for sub in plan.subgoals:
            assert sub.status == "pending"
            for task in sub.tasks:
                assert task.status == "pending"


# ── plan() with no LLM ────────────────────────────────────────────────


class TestPlanFallback:
    @pytest.mark.asyncio
    async def test_falls_back_when_no_llm(self, planner: HierarchicalPlanner) -> None:
        # No llm_call configured → uses plan_offline path.
        plan = await planner.plan("anything")
        assert isinstance(plan, HierarchicalPlan)
        assert plan.goal == "anything"
        assert plan.metadata["source"] == "offline"


# ── execute_subgoal ───────────────────────────────────────────────────


class TestExecuteSubgoal:
    def test_no_tasks_returns_done(self, planner: HierarchicalPlanner) -> None:
        sub = SubPlan(subgoal_id="x", title="t", description="d")
        result = planner.execute_subgoal(sub)
        assert isinstance(result, TaskResult)
        assert result.status == "done"
        assert result.succeeded is True

    def test_executes_registered_tools(self, planner: HierarchicalPlanner) -> None:
        planner.register_tool_executor("adder", lambda **kw: kw["a"] + kw["b"])
        sub = SubPlan(
            subgoal_id="s", title="t", description="d",
            tasks=[
                TaskSpec(task_id="t1", description="add", tool="adder", inputs={"a": 1, "b": 2}),
            ],
        )
        result = planner.execute_subgoal(sub)
        assert result.status == "done"
        assert result.succeeded is True
        assert sub.tasks[0].status == "done"
        assert sub.tasks[0].output == 3

    def test_dependency_ordering(self, planner: HierarchicalPlanner) -> None:
        order: list[str] = []

        def make_executor(label: str):
            def fn(**_kw):
                order.append(label)
                return label
            return fn

        planner.register_tool_executor("first", make_executor("first"))
        planner.register_tool_executor("second", make_executor("second"))

        sub = SubPlan(
            subgoal_id="s", title="t", description="d",
            tasks=[
                TaskSpec(task_id="t1", description="first", tool="first", inputs={}),
                TaskSpec(task_id="t2", description="second", tool="second", inputs={}, depends_on=["t1"]),
            ],
        )
        planner.execute_subgoal(sub)
        assert order == ["first", "second"]

    def test_unknown_tool_skipped(self, planner: HierarchicalPlanner) -> None:
        sub = SubPlan(
            subgoal_id="s", title="t", description="d",
            tasks=[TaskSpec(task_id="t1", description="x", tool="nope", inputs={})],
        )
        result = planner.execute_subgoal(sub)
        assert result.status == "done"  # no failure, just skipped
        assert sub.tasks[0].status == "skipped"

    def test_exception_marks_failed(self, planner: HierarchicalPlanner) -> None:
        def boom(**_):
            raise RuntimeError("kaboom")

        planner.register_tool_executor("boom", boom)
        sub = SubPlan(
            subgoal_id="s", title="t", description="d",
            tasks=[TaskSpec(task_id="t1", description="x", tool="boom", inputs={})],
        )
        result = planner.execute_subgoal(sub)
        assert result.status == "failed"
        assert result.succeeded is False


# ── get_progress ──────────────────────────────────────────────────────


class TestGetProgress:
    def test_empty_plan_is_complete(self, planner: HierarchicalPlanner) -> None:
        plan = HierarchicalPlan(plan_id="p", goal="g", context="")
        assert planner.get_progress(plan) == 1.0

    def test_pending_plan_zero(self, planner: HierarchicalPlanner, sample_subgoals: list[dict]) -> None:
        plan = planner.plan_offline("g", sample_subgoals)
        assert planner.get_progress(plan) == 0.0

    def test_partial_progress(self, planner: HierarchicalPlanner, sample_subgoals: list[dict]) -> None:
        plan = planner.plan_offline("g", sample_subgoals)
        # Mark first task done, second skipped.
        plan.subgoals[0].tasks[0].status = "done"
        plan.subgoals[0].tasks[1].status = "skipped"
        # 2 of 3 total tasks done.
        assert planner.get_progress(plan) == round(2 / 3, 4)


# ── Dataclass round-trips ─────────────────────────────────────────────


class TestDataclasses:
    def test_task_spec_roundtrip(self) -> None:
        t = TaskSpec(task_id="x", description="d", tool="t", inputs={"k": 1})
        d = t.to_dict()
        assert d["task_id"] == "x"
        assert d["tool"] == "t"
        assert d["inputs"] == {"k": 1}

    def test_subplan_all_tasks(self) -> None:
        sub = SubPlan(
            subgoal_id="s", title="t", description="d",
            tasks=[TaskSpec(task_id="1", description="a"), TaskSpec(task_id="2", description="b")],
        )
        plan = HierarchicalPlan(plan_id="p", goal="g", context="", subgoals=[sub])
        assert len(plan.all_tasks) == 2

    def test_task_result_succeeded(self) -> None:
        r = TaskResult(subgoal_id="s", status="done")
        assert r.succeeded is True
        r2 = TaskResult(subgoal_id="s", status="failed", error="x")
        assert r2.succeeded is False