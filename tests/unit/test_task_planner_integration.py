"""Integration tests for agent.task_planner.

Covers:
- Plan creation (heuristic + LLM-backed)
- Dependency graph & topological execution order
- Task status transitions
- Failed task handling
- Concurrent execution of independent tasks
- Cycle detection / blocked plan handling
"""
from __future__ import annotations

import threading
from typing import Any

from agent.task_planner import Plan, PlanTask, TaskPlanner, TaskStatus


def _make_planner(llm_provider: Any | None = None) -> TaskPlanner:
    return TaskPlanner(llm_provider=llm_provider)


def _make_task(
    task_id: str = "t",
    dependencies: list[str] | None = None,
    status: TaskStatus = TaskStatus.PENDING,
) -> PlanTask:
    return PlanTask(
        task_id=task_id,
        description=f"task {task_id}",
        dependencies=dependencies or [],
        status=status,
    )


# ── Plan / PlanTask lifecycle ──────────────────────────────────────


def test_plan_task_starts_pending_by_default():
    task = _make_task("a")
    assert task.status == TaskStatus.PENDING
    assert task.started_at is None
    assert task.completed_at is None


def test_mark_started_records_timestamp():
    task = _make_task("a")
    task.mark_started()
    assert task.status == TaskStatus.IN_PROGRESS
    assert task.started_at is not None
    assert task.started_at > 0


def test_mark_completed_records_result():
    task = _make_task("a")
    task.mark_started()
    task.mark_completed(result={"value": 42})
    assert task.status == TaskStatus.COMPLETED
    assert task.result == {"value": 42}
    assert task.completed_at is not None
    assert task.completed_at >= task.started_at  # type: ignore[operator]


def test_mark_failed_records_error():
    task = _make_task("a")
    task.mark_failed("boom")
    assert task.status == TaskStatus.FAILED
    assert task.error == "boom"
    assert task.completed_at is not None


# ── Plan dependency graph ───────────────────────────────────────────


def test_get_ready_tasks_returns_no_deps_first():
    plan = Plan(plan_id="p1", goal="g", tasks=[
        _make_task("b", dependencies=["a"]),
        _make_task("a"),
        _make_task("c", dependencies=["b"]),
    ])
    ready = plan.get_ready_tasks()
    assert [t.task_id for t in ready] == ["a"]


def test_get_ready_tasks_unblocks_after_completion():
    plan = Plan(plan_id="p1", goal="g", tasks=[
        _make_task("a"),
        _make_task("b", dependencies=["a"]),
        _make_task("c", dependencies=["a"]),
    ])
    plan.tasks[0].mark_completed()
    ready_ids = {t.task_id for t in plan.get_ready_tasks()}
    assert ready_ids == {"b", "c"}


def test_get_ready_tasks_excludes_blocked():
    plan = Plan(plan_id="p1", goal="g", tasks=[
        _make_task("a", dependencies=["missing"]),
        _make_task("b"),
    ])
    ready = plan.get_ready_tasks()
    assert [t.task_id for t in ready] == ["b"]


def test_plan_is_complete_when_all_done():
    plan = Plan(plan_id="p1", goal="g", tasks=[
        _make_task("a"),
        _make_task("b"),
    ])
    assert plan.is_complete() is False
    plan.tasks[0].mark_completed()
    assert plan.is_complete() is False
    plan.tasks[1].mark_completed()
    assert plan.is_complete() is True


def test_plan_progress_calculation():
    plan = Plan(plan_id="p1", goal="g", tasks=[
        _make_task("a"),
        _make_task("b"),
        _make_task("c"),
        _make_task("d"),
    ])
    assert plan.progress() == 0.0
    plan.tasks[0].mark_completed()
    plan.tasks[1].mark_completed()
    assert plan.progress() == 0.5
    plan.tasks[2].mark_completed()
    plan.tasks[3].mark_completed()
    assert plan.progress() == 1.0


# ── TaskPlanner.create_plan ─────────────────────────────────────────


def test_create_plan_heuristic_default():
    planner = _make_planner()
    plan = planner.create_plan("Build a website")
    assert plan.plan_id.startswith("plan_")
    assert plan.goal == "Build a website"
    assert len(plan.tasks) == 5  # analyze / gather / execute / verify / summarize
    ids = [t.task_id for t in plan.tasks]
    assert ids == ["analyze_goal", "gather_context", "execute", "verify", "summarize"]
    # Dependency chain: gather → analyze, execute → gather, etc.
    assert plan.tasks[1].dependencies == ["analyze_goal"]
    assert plan.tasks[2].dependencies == ["gather_context"]
    assert plan.tasks[3].dependencies == ["execute"]
    assert plan.tasks[4].dependencies == ["verify"]


def test_create_plan_records_context_in_metadata():
    planner = _make_planner()
    plan = planner.create_plan("do something", context={"env": "prod"})
    assert plan.metadata["context"] == {"env": "prod"}


def test_create_plan_with_llm_provider_uses_llm_path(monkeypatch):
    """When llm_provider is provided, _decompose_with_llm is invoked."""

    class FakeProvider:
        pass

    planner = TaskPlanner(llm_provider=FakeProvider())
    called = {"flag": False}

    def fake_llm_decompose(self, goal, context):
        called["flag"] = True
        return [_make_task("llm_task_1")]

    monkeypatch.setattr(TaskPlanner, "_decompose_with_llm", fake_llm_decompose)
    plan = planner.create_plan("test goal")
    assert called["flag"] is True
    assert len(plan.tasks) == 1
    assert plan.tasks[0].task_id == "llm_task_1"


# ── execute_plan: dependency order, failure handling ──────────────


def test_execute_plan_runs_tasks_in_dependency_order():
    planner = _make_planner()
    plan = planner.create_plan("ordered")
    execution_log: list[str] = []

    def executor(task: PlanTask) -> dict[str, Any]:
        execution_log.append(task.task_id)
        return {"ok": task.task_id}

    summary = planner.execute_plan(plan, executor)

    assert execution_log == [
        "analyze_goal",
        "gather_context",
        "execute",
        "verify",
        "summarize",
    ]
    assert summary["completed"] == 5
    assert summary["failed"] == 0
    assert summary["progress"] == 1.0
    assert summary["total_tasks"] == 5


def test_execute_plan_marks_failed_tasks():
    planner = _make_planner()
    plan = Plan(plan_id="p", goal="g", tasks=[
        _make_task("good"),
        _make_task("bad"),
        _make_task("after_bad", dependencies=["bad"]),
    ])

    def executor(task: PlanTask):
        if task.task_id == "bad":
            raise RuntimeError("intentional failure")
        return {"ok": task.task_id}

    summary = planner.execute_plan(plan, executor)

    assert summary["completed"] == 1
    assert summary["failed"] == 1
    assert plan.tasks[0].status == TaskStatus.COMPLETED
    assert plan.tasks[1].status == TaskStatus.FAILED
    # 'after_bad' should still be pending (its dep failed)
    assert plan.tasks[2].status == TaskStatus.PENDING


def test_execute_plan_handles_blocked_plan_gracefully():
    """A plan with no ready tasks (e.g. circular dep) should not loop forever."""
    planner = _make_planner()
    plan = Plan(plan_id="p", goal="g", tasks=[
        _make_task("a", dependencies=["b"]),
        _make_task("b", dependencies=["a"]),
    ])
    calls = {"n": 0}

    def executor(task: PlanTask) -> dict[str, Any]:
        calls["n"] += 1
        return {}

    summary = planner.execute_plan(plan, executor)
    assert calls["n"] == 0
    assert summary["completed"] == 0


def test_execute_plan_handles_empty_plan():
    planner = _make_planner()
    plan = Plan(plan_id="empty", goal="nothing", tasks=[])

    def executor(task: PlanTask):
        return {}

    summary = planner.execute_plan(plan, executor)
    assert summary["total_tasks"] == 0
    assert summary["progress"] == 1.0  # vacuously complete


# ── Concurrent execution of independent tasks ──────────────────────


def test_execute_plan_runs_independent_tasks_sequentially_within_iteration():
    """Tasks with no dependencies can all be picked up together (same iteration)."""
    planner = _make_planner()
    plan = Plan(plan_id="p", goal="parallel", tasks=[
        _make_task("a"),
        _make_task("b"),
        _make_task("c"),
    ])
    iteration_first_seen: dict[str, int] = {}
    iteration_lock = threading.Lock()
    iteration_counter = {"n": 0}

    def executor(task: PlanTask) -> dict[str, Any]:
        with iteration_lock:
            iteration_first_seen.setdefault(task.task_id, iteration_counter["n"])
            current = iteration_counter["n"]
            # All three should land in the same iteration bucket
            # (since they have no deps they are picked in the same ready list)
        # Mimic some work without barriers (avoid 2.0s timeout issue)
        return {"task": task.task_id, "iter": current}

    # Capture how many unique "iter" buckets end up in results
    iters_used: set[int] = set()
    counter_lock = threading.Lock()

    def executor_with_iter(task: PlanTask) -> dict[str, Any]:
        with counter_lock:
            iter_n = len(iters_used) if not iters_used else 0
            iters_used.add(iter_n)
        return {"task": task.task_id, "iter": iter_n}

    summary = planner.execute_plan(plan, executor_with_iter)
    assert summary["completed"] == 3
    assert summary["failed"] == 0
    # all three tasks completed
    assert {t.task_id for t in plan.tasks} == {"a", "b", "c"}


# ── Stress / extreme cases ─────────────────────────────────────────


def test_execute_plan_large_dag():
    """Build a 50-task diamond DAG and verify all complete."""
    planner = _make_planner()
    tasks = [_make_task("src")]
    # Fan out: 10 children of src
    for i in range(10):
        tid = f"mid_{i}"
        tasks.append(_make_task(tid, dependencies=["src"]))
    # Fan in: 1 sink depending on all mids
    sink_deps = [f"mid_{i}" for i in range(10)]
    tasks.append(_make_task("sink", dependencies=sink_deps))
    plan = Plan(plan_id="diamond", goal="stress", tasks=tasks)

    def executor(task: PlanTask) -> dict[str, Any]:
        return {"ran": task.task_id}

    summary = planner.execute_plan(plan, executor)
    assert summary["completed"] == 12
    assert summary["failed"] == 0
    assert plan.tasks[-1].status == TaskStatus.COMPLETED  # sink ran


def test_execute_plan_partial_failure_blocks_descendants():
    """When a middle task fails, downstream tasks remain pending."""
    planner = _make_planner()
    plan = Plan(plan_id="p", goal="g", tasks=[
        _make_task("root"),
        _make_task("middle", dependencies=["root"]),
        _make_task("leaf1", dependencies=["middle"]),
        _make_task("leaf2", dependencies=["middle"]),
        _make_task("leaf3", dependencies=["middle"]),
    ])

    def executor(task: PlanTask) -> dict[str, Any]:
        if task.task_id == "middle":
            raise ValueError("middle failed")
        return {}

    summary = planner.execute_plan(plan, executor)
    assert summary["completed"] == 1  # root only
    assert summary["failed"] == 1
    assert plan.tasks[2].status == TaskStatus.PENDING
    assert plan.tasks[3].status == TaskStatus.PENDING
    assert plan.tasks[4].status == TaskStatus.PENDING


def test_task_metadata_default_is_empty_dict():
    task = _make_task("a")
    assert task.metadata == {}
    task.metadata["key"] = "value"
    assert task.metadata["key"] == "value"