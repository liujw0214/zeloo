"""Task planner — decompose complex goals into executable plan."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class TaskStatus(StrEnum):
    """Status of a plan task."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


@dataclass
class PlanTask:
    """A single task in a plan."""

    task_id: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    dependencies: list[str] = field(default_factory=list)
    tool_hint: str = ""
    estimated_complexity: int = 1  # 1-10
    result: Any = None
    error: str = ""
    started_at: float | None = None
    completed_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def mark_started(self) -> None:
        self.status = TaskStatus.IN_PROGRESS
        self.started_at = time.time()

    def mark_completed(self, result: Any = None) -> None:
        self.status = TaskStatus.COMPLETED
        self.completed_at = time.time()
        self.result = result

    def mark_failed(self, error: str) -> None:
        self.status = TaskStatus.FAILED
        self.completed_at = time.time()
        self.error = error


@dataclass
class Plan:
    """A plan consisting of multiple tasks."""

    plan_id: str
    goal: str
    tasks: list[PlanTask] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_ready_tasks(self) -> list[PlanTask]:
        """Get tasks that are ready to be executed (dependencies met)."""
        completed_ids = {
            t.task_id for t in self.tasks
            if t.status == TaskStatus.COMPLETED
        }
        return [
            t for t in self.tasks
            if t.status == TaskStatus.PENDING
            and all(dep in completed_ids for dep in t.dependencies)
        ]

    def is_complete(self) -> bool:
        return all(
            t.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED, TaskStatus.FAILED)
            for t in self.tasks
        )

    def progress(self) -> float:
        if not self.tasks:
            return 1.0
        completed = sum(
            1 for t in self.tasks
            if t.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED)
        )
        return completed / len(self.tasks)


class TaskPlanner:
    """Decompose complex goals into structured executable plans.

    Uses heuristic decomposition rules to split a goal into tasks
    that can be executed sequentially or in parallel.
    """

    def __init__(self, llm_provider: Any | None = None) -> None:
        self.llm_provider = llm_provider

    def create_plan(
        self,
        goal: str,
        context: dict[str, Any] | None = None,
    ) -> Plan:
        """Create a plan for the given goal.

        Args:
            goal: High-level goal description.
            context: Optional context (available tools, environment info).
        """
        plan_id = f"plan_{uuid.uuid4().hex[:8]}"
        plan = Plan(plan_id=plan_id, goal=goal)

        if self.llm_provider is not None:
            tasks = self._decompose_with_llm(goal, context)
        else:
            tasks = self._decompose_heuristic(goal)

        plan.tasks = tasks
        plan.metadata = {"context": context or {}}
        logger.info("Created plan %s with %d tasks for goal: %s",
                    plan_id, len(tasks), goal[:60])
        return plan

    def _decompose_heuristic(self, goal: str) -> list[PlanTask]:
        """Heuristic task decomposition."""
        tasks = [
            PlanTask(
                task_id="analyze_goal",
                description=f"Analyze goal and identify required resources: {goal}",
                tool_hint="reasoning",
                estimated_complexity=2,
            ),
            PlanTask(
                task_id="gather_context",
                description="Gather relevant context and prerequisites",
                tool_hint="file_read",
                dependencies=["analyze_goal"],
                estimated_complexity=3,
            ),
            PlanTask(
                task_id="execute",
                description=f"Execute primary work for: {goal}",
                tool_hint="execute_code",
                dependencies=["gather_context"],
                estimated_complexity=7,
            ),
            PlanTask(
                task_id="verify",
                description="Verify results and check for errors",
                tool_hint="execute_code",
                dependencies=["execute"],
                estimated_complexity=3,
            ),
            PlanTask(
                task_id="summarize",
                description="Summarize outcome and report",
                tool_hint="reasoning",
                dependencies=["verify"],
                estimated_complexity=1,
            ),
        ]
        return tasks

    def _decompose_with_llm(
        self,
        goal: str,
        context: dict[str, Any] | None,
        llm_caller: Any | None = None,
    ) -> list[PlanTask]:
        """Decompose using an LLM caller.

        Falls back to heuristic decomposition if no llm_caller is provided
        or the LLM call fails. The expected llm_caller signature is::

            result = llm_caller(messages: list[dict]) -> dict
            result = {"content": "...", "tool_calls": [...], ...}
        """
        if llm_caller is None:
            logger.debug("No LLM caller, falling back to heuristic decomposition")
            return self._decompose_heuristic(goal)

        prompt = self._build_decomposition_prompt(goal, context or {})
        try:
            response = llm_caller([{"role": "user", "content": prompt}])
            content = response.get("content", "") if isinstance(response, dict) else ""
            return self._parse_llm_decomposition(content, goal)
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM decomposition failed (%s), using heuristic", exc)
            return self._decompose_heuristic(goal)

    def _build_decomposition_prompt(
        self,
        goal: str,
        context: dict[str, Any],
    ) -> str:
        """Build a structured prompt asking the LLM to decompose a goal."""
        ctx_text = "\n".join(f"- {k}: {v}" for k, v in context.items()) or "(no context)"
        return (
            f"You are a task planner. Decompose the following goal into 3-7 concrete tasks.\n"
            f"Goal: {goal}\nContext:\n{ctx_text}\n\n"
            f"Return ONLY a JSON array of tasks with this schema:\n"
            f'[{{"task_id": "unique_snake_id", "description": "...", "tool_hint": "...", '
            f'"dependencies": ["other_task_id"], "estimated_complexity": 1-10}}]\n'
            f"Do not include any prose outside the JSON array."
        )

    def _parse_llm_decomposition(
        self,
        content: str,
        goal: str,
    ) -> list[PlanTask]:
        """Parse LLM JSON output into PlanTask objects, with fallback."""
        import json as _json
        import re as _re

        match = _re.search(r"\[.*\]", content, _re.DOTALL)
        if not match:
            logger.warning("LLM output had no JSON array, using heuristic")
            return self._decompose_heuristic(goal)
        try:
            items = _json.loads(match.group(0))
        except _json.JSONDecodeError as exc:
            logger.warning("LLM JSON parse failed (%s), using heuristic", exc)
            return self._decompose_heuristic(goal)

        valid_ids = set()
        for item in items:
            if isinstance(item, dict) and "task_id" in item:
                valid_ids.add(item["task_id"])

        tasks: list[PlanTask] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            task_id = item.get("task_id", "")
            description = item.get("description", "")
            if not task_id or not description:
                continue
            deps = item.get("dependencies", []) or []
            deps = [d for d in deps if d in valid_ids]
            try:
                complexity = int(item.get("estimated_complexity", 5))
            except (TypeError, ValueError):
                complexity = 5
            complexity = max(1, min(10, complexity))
            tasks.append(
                PlanTask(
                    task_id=task_id,
                    description=description,
                    tool_hint=item.get("tool_hint", "reasoning"),
                    dependencies=deps,
                    estimated_complexity=complexity,
                )
            )
        if not tasks:
            logger.warning("LLM produced 0 valid tasks, using heuristic")
            return self._decompose_heuristic(goal)
        return tasks

    def execute_plan(
        self,
        plan: Plan,
        executor: Any,
    ) -> dict[str, Any]:
        """Execute plan tasks in dependency order.

        Args:
            plan: The plan to execute.
            executor: Callable that takes a task and returns its result.
        """
        logger.info("Executing plan %s with %d tasks", plan.plan_id, len(plan.tasks))
        while not plan.is_complete():
            ready = plan.get_ready_tasks()
            if not ready:
                logger.warning("Plan %s is blocked", plan.plan_id)
                break
            for task in ready:
                task.mark_started()
                try:
                    result = executor(task)
                    task.mark_completed(result)
                except Exception as e:
                    task.mark_failed(str(e))
                    logger.error("Task %s failed: %s", task.task_id, e)

        return {
            "plan_id": plan.plan_id,
            "progress": plan.progress(),
            "completed": sum(
                1 for t in plan.tasks if t.status == TaskStatus.COMPLETED
            ),
            "failed": sum(
                1 for t in plan.tasks if t.status == TaskStatus.FAILED
            ),
            "total_tasks": len(plan.tasks),
        }


__all__ = [
    "TaskStatus",
    "PlanTask",
    "Plan",
    "TaskPlanner",
]