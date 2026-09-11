"""Agent coordinator — orchestrate multiple agents working together."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):  # noqa: UP042
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    """A unit of work assigned to an agent."""

    id: str
    description: str
    assignee: str
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: str | None = None
    created_at: float = field(default_factory=datetime.now().timestamp)
    started_at: float | None = None
    completed_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskResult:
    """Result of a task execution."""

    task_id: str
    success: bool
    output: Any
    error: str | None = None
    duration_seconds: float = 0.0
    agent_name: str = ""


class AgentCoordinator:
    """Coordinate multiple agents working on a shared set of tasks.

    Features:
    - Task distribution across agents
    - Sequential and parallel execution
    - Task dependencies (DAG)
    - Result aggregation
    - Cancellation support
    """

    def __init__(self, agents: dict[str, Any] | None = None):
        self.agents = agents or {}
        self._tasks: dict[str, Task] = {}
        self._lock = threading.Lock()
        self._results: dict[str, TaskResult] = {}
        self._task_counter = 0

    def add_agent(self, name: str, agent: Any) -> None:
        """Register an agent by name."""
        self.agents[name] = agent
        logger.info("Agent registered: %s", name)

    def create_task(
        self,
        description: str,
        assignee: str,
        depends_on: list[str] | None = None,
    ) -> str:
        """Create a new task and return its ID."""
        task_id = f"task-{self._task_counter}"
        self._task_counter += 1

        task = Task(
            id=task_id,
            description=description,
            assignee=assignee,
            metadata={"depends_on": depends_on or []},
        )
        with self._lock:
            self._tasks[task_id] = task

        logger.info("Task created: %s (assignee=%s)", task_id, assignee)
        return task_id

    def get_task(self, task_id: str) -> Task | None:
        """Retrieve a task by ID."""
        return self._tasks.get(task_id)

    def run_task(self, task_id: str) -> TaskResult:
        """Execute a single task with the assigned agent."""
        task = self._tasks.get(task_id)
        if not task:
            return TaskResult(task_id=task_id, success=False, output=None, error="Task not found")

        agent = self.agents.get(task.assignee)
        if not agent:
            return TaskResult(
                task_id=task_id, success=False, output=None, error="Agent not found"
            )

        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now().timestamp()
        start = task.started_at

        try:
            logger.info("Running task %s on agent %s", task_id, task.assignee)
            output = agent.run_conversation(task.description)
            duration = datetime.now().timestamp() - start
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now().timestamp()
            task.result = output

            result = TaskResult(
                task_id=task_id,
                success=True,
                output=output,
                duration_seconds=duration,
                agent_name=task.assignee,
            )
            with self._lock:
                self._results[task_id] = result
            return result

        except Exception as e:
            duration = datetime.now().timestamp() - start
            task.status = TaskStatus.FAILED
            task.completed_at = datetime.now().timestamp()
            task.error = str(e)

            result = TaskResult(
                task_id=task_id, success=False, output=None, error=str(e),
                duration_seconds=duration, agent_name=task.assignee,
            )
            with self._lock:
                self._results[task_id] = result
            logger.error("Task %s failed: %s", task_id, e)
            return result

    def run_all(
        self,
        ordered: bool = False,
    ) -> dict[str, TaskResult]:
        """Run all pending tasks.

        Args:
            ordered: If True, respect dependency order. If False, run in parallel.

        Returns:
            Dict mapping task_id to TaskResult.
        """
        pending = [t for t in self._tasks.values() if t.status == TaskStatus.PENDING]
        if ordered:
            return self._run_ordered(pending)
        return self._run_parallel(pending)

    def _run_parallel(self, tasks: list[Task]) -> dict[str, TaskResult]:
        threads: dict[str, threading.Thread] = {}
        results: dict[str, TaskResult] = {}

        for task in tasks:
            t = threading.Thread(
                target=lambda tid: results.update({tid: self.run_task(tid)}),
                args=(task.id,),
                name=f"task-{task.id}",
            )
            threads[task.id] = t
            t.start()

        for tid, t in threads.items():
            t.join()
            results[tid] = self._results.get(
                tid,
                TaskResult(task_id=tid, success=False, output=None, error="Result not found"),
            )

        return results

    def _run_ordered(self, tasks: list[Task]) -> dict[str, TaskResult]:
        results: dict[str, TaskResult] = {}
        completed: set[str] = set()

        for task in tasks:
            deps = task.metadata.get("depends_on", [])
            for dep_id in deps:
                prev = self._results.get(dep_id)
                dep_ok = dep_id in completed or (prev is not None and prev.success)
                if not dep_ok:
                    logger.warning("Dependency %s not met for task %s", dep_id, task.id)

            result = self.run_task(task.id)
            results[task.id] = result
            if result.success:
                completed.add(task.id)

        return results

    def get_results(self) -> dict[str, TaskResult]:
        return dict(self._results)

    def summarize(self) -> dict[str, Any]:
        total = len(self._tasks)
        completed = sum(1 for t in self._tasks.values() if t.status == TaskStatus.COMPLETED)
        failed = sum(1 for t in self._tasks.values() if t.status == TaskStatus.FAILED)
        running = sum(1 for t in self._tasks.values() if t.status == TaskStatus.RUNNING)
        pending = sum(1 for t in self._tasks.values() if t.status == TaskStatus.PENDING)
        return {
            "total": total,
            "completed": completed,
            "failed": failed,
            "running": running,
            "pending": pending,
            "success_rate": round(completed / total, 2) if total else 0.0,
        }
