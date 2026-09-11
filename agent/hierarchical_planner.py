"""Hierarchical planner — multi-level DAG: Goal → SubGoal → Task."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

DEFAULT_PLANS_DIR = Path.home() / ".Zeloo" / "cache" / "hierarchical_planner"


@dataclass
class TaskSpec:
    """Leaf-level task description."""

    task_id: str
    description: str
    tool: str | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    status: str = "pending"  # pending | running | done | failed | skipped
    output: Any | None = None
    started_at: float | None = None
    finished_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id, "description": self.description,
            "tool": self.tool, "inputs": self.inputs, "depends_on": self.depends_on,
            "status": self.status, "output": self.output,
            "started_at": self.started_at, "finished_at": self.finished_at,
        }


@dataclass
class SubPlan:
    """A SubGoal and its associated leaf tasks."""

    subgoal_id: str
    title: str
    description: str
    tasks: list[TaskSpec] = field(default_factory=list)
    status: str = "pending"
    success_criteria: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "subgoal_id": self.subgoal_id, "title": self.title,
            "description": self.description, "tasks": [t.to_dict() for t in self.tasks],
            "status": self.status, "success_criteria": self.success_criteria,
        }


@dataclass
class HierarchicalPlan:
    """Top-level plan rooted at a single goal."""

    plan_id: str
    goal: str
    context: str
    subgoals: list[SubPlan] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id, "goal": self.goal, "context": self.context,
            "subgoals": [s.to_dict() for s in self.subgoals],
            "created_at": self.created_at, "metadata": self.metadata,
        }

    @property
    def all_tasks(self) -> list[TaskSpec]:
        return [t for s in self.subgoals for t in s.tasks]


@dataclass
class TaskResult:
    """Outcome of executing a single SubPlan."""

    subgoal_id: str
    status: str
    task_results: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    completed_at: float = field(default_factory=time.time)

    @property
    def succeeded(self) -> bool:
        return self.status == "done" and self.error is None


class HierarchicalPlanner:
    """Multi-level planner: Goal → SubGoal → Task."""

    def __init__(
        self,
        llm_provider: str = "anthropic",
        llm_model: str = "claude-3-5-sonnet",
        llm_call: Callable[..., Any] | None = None,
        plans_dir: Path | None = None,
    ) -> None:
        self.llm_provider = llm_provider
        self.llm_model = llm_model
        self.llm_call = llm_call
        self.plans_dir = Path(plans_dir) if plans_dir else DEFAULT_PLANS_DIR
        self.plans_dir.mkdir(parents=True, exist_ok=True)
        self._tool_executors: dict[str, Callable[..., Any]] = {}

    def register_tool_executor(self, tool: str, fn: Callable[..., Any]) -> None:
        """Register a function used to execute a leaf task's ``tool``."""
        self._tool_executors[tool] = fn

    async def plan(self, goal: str, context: str = "") -> HierarchicalPlan:
        """Build a plan by calling the LLM planner."""
        if self.llm_call is None:
            return self.plan_offline(goal, predefined_subgoals=[
                {"title": "Understand goal", "description": goal,
                 "tasks": [{"description": "Parse goal and extract constraints"}]},
            ])
        raw = await self._invoke_llm(self._build_prompt(goal, context))
        try:
            return self._parse_llm_response(raw, goal, context)
        except Exception as exc:
            logger.warning("LLM planner returned malformed response (%s); using offline fallback", exc)
            return self.plan_offline(goal, predefined_subgoals=[
                {"title": "Understand goal", "description": goal,
                 "tasks": [{"description": "Parse goal and extract constraints"}]},
            ])

    def plan_offline(
        self,
        goal: str,
        predefined_subgoals: list[dict[str, Any]],
    ) -> HierarchicalPlan:
        """Assemble a plan from a caller-supplied subgoal list (no LLM)."""
        plan = HierarchicalPlan(
            plan_id=uuid.uuid4().hex, goal=goal, context="", metadata={"source": "offline"},
        )
        for sg in predefined_subgoals:
            sub = SubPlan(
                subgoal_id=uuid.uuid4().hex[:8],
                title=str(sg.get("title", "Subgoal")),
                description=str(sg.get("description", "")),
                success_criteria=sg.get("success_criteria"),
            )
            for t in sg.get("tasks", []):
                sub.tasks.append(TaskSpec(
                    task_id=uuid.uuid4().hex[:8],
                    description=str(t.get("description", "")),
                    tool=t.get("tool"),
                    inputs=dict(t.get("inputs", {})),
                    depends_on=list(t.get("depends_on", [])),
                ))
            plan.subgoals.append(sub)
        self._persist_plan(plan)
        return plan

    def execute_subgoal(self, subgoal: SubPlan) -> TaskResult:
        """Execute the leaf tasks of ``subgoal`` respecting dependencies."""
        if not subgoal.tasks:
            return TaskResult(subgoal_id=subgoal.subgoal_id, status="done")
        by_id = {t.task_id: t for t in subgoal.tasks}
        completed: dict[str, Any] = {}
        results: list[dict[str, Any]] = []
        any_failed = False
        pending = {t.task_id for t in subgoal.tasks}
        while pending:
            ready = [tid for tid in pending
                     if all(dep in completed or dep not in by_id for dep in by_id[tid].depends_on)]
            if not ready:
                for tid in pending:
                    by_id[tid].status = "skipped"
                    results.append({"task_id": tid, "status": "skipped"})
                break
            for tid in ready:
                task = by_id[tid]
                pending.discard(tid)
                task.status = "running"
                task.started_at = time.time()
                executor = self._tool_executors.get(task.tool or "")
                if executor is None:
                    task.status = "skipped"
                    task.output = f"no executor registered for tool {task.tool!r}"
                else:
                    try:
                        task.output = executor(**task.inputs)
                        task.status = "done"
                    except Exception as exc:
                        task.status = "failed"
                        task.output = f"{type(exc).__name__}: {exc}"
                        any_failed = True
                task.finished_at = time.time()
                completed[tid] = task.output
                results.append({"task_id": tid, "status": task.status, "output": task.output})
        status = "failed" if any_failed else "done"
        subgoal.status = status
        return TaskResult(
            subgoal_id=subgoal.subgoal_id, status=status, task_results=results,
            error=None if status == "done" else "one or more tasks failed",
        )

    def get_progress(self, plan: HierarchicalPlan) -> float:
        """Return plan completion progress in ``[0.0, 1.0]``."""
        total = sum(len(s.tasks) for s in plan.subgoals)
        if total == 0:
            return 1.0
        done = sum(1 for s in plan.subgoals for t in s.tasks if t.status in ("done", "skipped"))
        return round(done / total, 4)

    def _build_prompt(self, goal: str, context: str) -> str:
        return (
            "Decompose the GOAL below into a hierarchical plan of subgoals "
            "and leaf tasks. Reply ONLY with a JSON object: {\"subgoals\": [{\"title\": str, "
            "\"description\": str, \"success_criteria\": str|null, \"tasks\": [{\"description\": str, "
            "\"tool\": str|null, \"inputs\": object, \"depends_on\": [str]}]}]}\n\n"
            f"GOAL: {goal}\nCONTEXT: {context}"
        )

    async def _invoke_llm(self, prompt: str) -> str:
        result = self.llm_call(provider=self.llm_provider, model=self.llm_model, prompt=prompt)
        if asyncio.iscoroutine(result):
            return await result
        return result

    def _parse_llm_response(self, raw: str, goal: str, context: str) -> HierarchicalPlan:
        data = json.loads(raw)
        plan = HierarchicalPlan(
            plan_id=uuid.uuid4().hex, goal=goal, context=context,
            metadata={"source": "llm", "provider": self.llm_provider, "model": self.llm_model},
        )
        for sg in data.get("subgoals", []):
            sub = SubPlan(
                subgoal_id=uuid.uuid4().hex[:8],
                title=str(sg.get("title", "Subgoal")),
                description=str(sg.get("description", "")),
                success_criteria=sg.get("success_criteria"),
            )
            for t in sg.get("tasks", []):
                sub.tasks.append(TaskSpec(
                    task_id=uuid.uuid4().hex[:8],
                    description=str(t.get("description", "")),
                    tool=t.get("tool"),
                    inputs=dict(t.get("inputs", {})),
                    depends_on=list(t.get("depends_on", [])),
                ))
            plan.subgoals.append(sub)
        self._persist_plan(plan)
        return plan

    def _persist_plan(self, plan: HierarchicalPlan) -> None:
        path = self.plans_dir / f"{plan.plan_id}.json"
        try:
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(plan.to_dict(), indent=2), encoding="utf-8")
            tmp.replace(path)
        except OSError as exc:
            logger.warning("Failed to persist plan %s: %s", plan.plan_id, exc)