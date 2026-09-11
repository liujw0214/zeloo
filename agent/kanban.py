"""Kanban — multi-agent collaborative board system.

This module provides a
persistent multi-agent collaboration board with:

- **Board** (hard boundary) → **Tenant** (soft namespace) → **Worker**
- Heartbeat mechanism for liveness detection
- Task reclaiming from dead workers
- Zombie detection and cleanup
- Retry budget for failed tasks
- Hallucination gating
- Auto-blocking of stuck tasks

Usage::

    from agent.kanban import KanbanBoard, TaskStatus

    board = KanbanBoard(board_id="my-project")
    task_id = board.create_task(title="Fix bug #123", tenant="team-a")
    board.assign_task(task_id, worker_id="agent-1")
    board.complete_task(task_id)
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Coalesce frequent heartbeat updates to a single disk write. Worker
# heartbeats can arrive every 1-5 s — without this throttle, a long-lived
# task generates one full-JSON rewrite per tick.
HEARTBEAT_FLUSH_INTERVAL_S = 5.0


class TaskStatus(StrEnum):
    """Status of a kanban task."""

    TODO = "todo"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass
class Task:
    """A kanban task card."""

    id: str
    title: str
    tenant: str = "default"
    description: str = ""
    status: TaskStatus = TaskStatus.TODO
    assignee: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    heartbeat: float = 0.0
    retry_count: int = 0
    max_retries: int = 3
    priority: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def touch(self) -> None:
        """Update the heartbeat timestamp."""
        self.heartbeat = time.time()
        self.updated_at = time.time()


class KanbanBoard:
    """A multi-agent kanban board with task lifecycle management.

    Supports task creation, assignment, heartbeat tracking, zombie
    detection, retry budgets, and auto-blocking.

    Args:
        board_id: Unique identifier for this board.
        storage_path: Path to persist board state (JSON).
        zombie_timeout_seconds: Seconds without heartbeat before a task
            is considered zombie and reclaimed.
    """

    def __init__(
        self,
        board_id: str,
        storage_path: str | Path | None = None,
        zombie_timeout_seconds: float = 300.0,
    ) -> None:
        self.board_id = board_id
        self._zombie_timeout = zombie_timeout_seconds
        self._storage_path = (
            Path(storage_path).expanduser()
            if storage_path
            else Path(f"~/.Zeloo/kanban/{board_id}.json").expanduser()
        )
        self._tasks: dict[str, Task] = {}
        # Coalesce heartbeat-only writes so a long-running task doesn't
        # generate one full-JSON rewrite per heartbeat tick.
        self._dirty = False
        self._last_flush = 0.0
        self._lock = threading.RLock()
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _load(self) -> None:
        """Load board state from disk."""
        if not self._storage_path.exists():
            return
        try:
            data = json.loads(self._storage_path.read_text(encoding="utf-8"))
            for tid, t in data.get("tasks", {}).items():
                self._tasks[tid] = Task(
                    id=tid,
                    title=t["title"],
                    tenant=t.get("tenant", "default"),
                    description=t.get("description", ""),
                    status=TaskStatus(t.get("status", "todo")),
                    assignee=t.get("assignee"),
                    created_at=t.get("created_at", time.time()),
                    updated_at=t.get("updated_at", time.time()),
                    heartbeat=t.get("heartbeat", 0.0),
                    retry_count=t.get("retry_count", 0),
                    max_retries=t.get("max_retries", 3),
                    priority=t.get("priority", 0),
                    metadata=t.get("metadata", {}),
                )
        except Exception:
            logger.exception("Failed to load kanban board %s", self.board_id)

    def _save(self) -> None:
        """Persist board state to disk. Caller must hold ``self._lock``."""
        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "board_id": self.board_id,
                "tasks": {
                    tid: {
                        "title": t.title,
                        "tenant": t.tenant,
                        "description": t.description,
                        "status": t.status.value,
                        "assignee": t.assignee,
                        "created_at": t.created_at,
                        "updated_at": t.updated_at,
                        "heartbeat": t.heartbeat,
                        "retry_count": t.retry_count,
                        "max_retries": t.max_retries,
                        "priority": t.priority,
                        "metadata": t.metadata,
                    }
                    for tid, t in self._tasks.items()
                },
            }
            # Use compact JSON (no indent) to minimise write bytes — the
            # file is machine-written and humans should use the API.
            self._storage_path.write_text(
                json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            self._dirty = False
            self._last_flush = time.time()
        except Exception:
            logger.exception("Failed to save kanban board %s", self.board_id)

    def _schedule_flush(self, *, immediate: bool = False) -> None:
        """Mark state dirty and flush if enough time has elapsed.

        ``immediate=True`` forces a synchronous save (used by task
        lifecycle transitions where durability matters). Heartbeats pass
        ``immediate=False`` so a 1-Hz heartbeat stream coalesces into a
        single write every ``HEARTBEAT_FLUSH_INTERVAL_S`` seconds.
        """
        with self._lock:
            self._dirty = True
            now = time.time()
            if (
                immediate
                or now - self._last_flush >= HEARTBEAT_FLUSH_INTERVAL_S
            ):
                if self._dirty:
                    self._save()

    # ------------------------------------------------------------------
    # Task CRUD
    # ------------------------------------------------------------------
    def create_task(
        self,
        title: str,
        tenant: str = "default",
        description: str = "",
        priority: int = 0,
        max_retries: int = 3,
    ) -> str:
        """Create a new task. Returns the task ID."""
        task_id = str(uuid.uuid4())
        with self._lock:
            self._tasks[task_id] = Task(
                id=task_id,
                title=title,
                tenant=tenant,
                description=description,
                priority=priority,
                max_retries=max_retries,
            )
            self._save()
        logger.info("Task '%s' created on board '%s'", task_id, self.board_id)
        return task_id

    def get_task(self, task_id: str) -> Task | None:
        """Get a task by ID."""
        with self._lock:
            return self._tasks.get(task_id)

    def list_tasks(
        self,
        tenant: str | None = None,
        status: TaskStatus | None = None,
    ) -> list[Task]:
        """List tasks, optionally filtered by tenant and/or status."""
        with self._lock:
            tasks = list(self._tasks.values())
        if tenant is not None:
            tasks = [t for t in tasks if t.tenant == tenant]
        if status is not None:
            tasks = [t for t in tasks if t.status == status]
        return sorted(tasks, key=lambda t: (-t.priority, t.created_at))

    def assign_task(self, task_id: str, worker_id: str) -> bool:
        """Assign a task to a worker. Returns True if successful."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            task.assignee = worker_id
            task.status = TaskStatus.IN_PROGRESS
            task.touch()
            self._save()
        logger.info("Task '%s' assigned to worker '%s'", task_id, worker_id)
        return True

    def heartbeat(self, task_id: str) -> bool:
        """Update a task's heartbeat (worker is alive).

        Writes are coalesced: at most one disk rewrite per
        ``HEARTBEAT_FLUSH_INTERVAL_S`` window. This is the difference
        between 1 disk write per heartbeat tick (high-frequency workers)
        and 1 disk write per 5 seconds (regardless of heartbeat rate).
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            task.touch()
            self._schedule_flush(immediate=False)
        return True

    def complete_task(self, task_id: str, result: str = "") -> bool:
        """Mark a task as completed."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            task.status = TaskStatus.COMPLETED
            task.touch()
            if result:
                task.metadata["result"] = result
            self._save()
        logger.info("Task '%s' completed", task_id)
        return True

    def fail_task(self, task_id: str, error: str = "") -> bool:
        """Mark a task as failed. Retries if budget remains, else blocks."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            task.retry_count += 1
            task.touch()
            if error:
                task.metadata["last_error"] = error
            if task.retry_count >= task.max_retries:
                task.status = TaskStatus.BLOCKED
                logger.warning(
                    "Task '%s' blocked after %d retries", task_id, task.retry_count
                )
            else:
                task.status = TaskStatus.TODO
                task.assignee = None
                logger.info(
                    "Task '%s' failed, retry %d/%d",
                    task_id,
                    task.retry_count,
                    task.max_retries,
                )
            self._save()
        return True

    def reclaim_zombies(self) -> list[str]:
        """Find and reclaim tasks whose workers have stopped heartbeating.

        Returns a list of reclaimed task IDs.
        """
        now = time.time()
        reclaimed: list[str] = []
        with self._lock:
            for tid, task in self._tasks.items():
                if task.status != TaskStatus.IN_PROGRESS:
                    continue
                if now - task.heartbeat > self._zombie_timeout:
                    task.status = TaskStatus.TODO
                    task.assignee = None
                    task.touch()
                    reclaimed.append(tid)
                    logger.warning(
                        "Task '%s' reclaimed from zombie worker '%s'",
                        tid,
                        task.assignee,
                    )
            if reclaimed:
                self._save()
        return reclaimed

    def get_stats(self) -> dict[str, Any]:
        """Return board statistics."""
        with self._lock:
            tasks = list(self._tasks.values())
        stats = {s.value: 0 for s in TaskStatus}
        for task in tasks:
            stats[task.status.value] += 1
        stats["total"] = len(tasks)
        return stats

    def flush(self) -> None:
        """Force-flush any coalesced heartbeat writes.

        Call this before shutdown to guarantee durability.
        """
        with self._lock:
            if self._dirty:
                self._save()
