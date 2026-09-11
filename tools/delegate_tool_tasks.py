"""High-level task management: create, track, cancel, resume delegated tasks."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DelegatedTask:
    """A delegated task with full lifecycle information."""

    task_id: str
    task_type: str
    params: dict[str, Any]
    config: Any
    submitted_at: float
    status: str
    result: Any = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "params": self.params,
            "submitted_at": self.submitted_at,
            "status": self.status,
            "result": self.result.to_dict() if hasattr(self.result, "to_dict") else self.result,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DelegatedTask:
        """Create from dictionary representation."""
        return cls(
            task_id=data["task_id"],
            task_type=data["task_type"],
            params=data["params"],
            config=data.get("config"),
            submitted_at=data["submitted_at"],
            status=data["status"],
            result=data.get("result"),
        )


class DelegatedTaskManager:
    """Manage the lifecycle of delegated tasks."""

    def __init__(self, storage_path: Path | None = None):
        self.storage_path = storage_path
        self.active_tasks: dict[str, DelegatedTask] = {}
        self._dispatcher = None
        self._progress_tracker = None
        self._history: list[DelegatedTask] = []

    def _get_dispatcher(self):
        """Get or create task dispatcher."""
        if self._dispatcher is None:
            from tools.delegate_tool_dispatch import TaskDispatcher
            self._dispatcher = TaskDispatcher()
        return self._dispatcher

    def _get_progress_tracker(self):
        """Get or create progress tracker."""
        if self._progress_tracker is None:
            from tools.delegate_tool_progress import TaskProgressTracker
            self._progress_tracker = TaskProgressTracker()
        return self._progress_tracker

    def _get_config(self, config: Any) -> Any:
        """Get or create delegate config."""
        if config is not None:
            return config
        from tools.delegate_tool_config import DelegateConfig
        return DelegateConfig()

    async def submit(
        self,
        task_type: str,
        params: dict[str, Any],
        config: Any = None,
    ) -> str:
        """Submit a new delegated task.

        Args:
            task_type: The type of task to execute.
            params: Parameters for the task.
            config: Optional execution configuration.

        Returns:
            The task ID.
        """
        from tools.delegate_tool_config import DelegateConfig

        task_id = str(uuid.uuid4())
        delegate_config = self._get_config(config)
        if delegate_config is None:
            delegate_config = DelegateConfig()

        task = DelegatedTask(
            task_id=task_id,
            task_type=task_type,
            params=params,
            config=delegate_config,
            submitted_at=time.time(),
            status="pending",
        )

        self.active_tasks[task_id] = task
        self._progress_tracker = self._get_progress_tracker()
        self._progress_tracker.start_tracking(task_id)

        if self.storage_path:
            await self._persist_task(task)

        logger.info("Submitted task %s of type %s", task_id, task_type)
        return task_id

    async def execute(self, task_id: str) -> Any:
        """Execute a submitted task.

        Args:
            task_id: The task ID to execute.

        Returns:
            TaskResult from execution.
        """
        from tools.delegate_tool_child_run import TaskResult
        from tools.delegate_tool_config import DelegateConfig

        task = self.active_tasks.get(task_id)
        if not task:
            return TaskResult(
                task_id=task_id,
                exit_code=-1,
                stdout="",
                stderr="Task not found",
                duration=0.0,
                timed_out=False,
                memory_peak_mb=0.0,
            )

        task.status = "running"
        dispatcher = self._get_dispatcher()
        progress = self._get_progress_tracker()
        progress.update(task_id, 1, "Executing task")

        command = task.params.get("command", "")
        if not command:
            command = task.params.get("prompt", "")

        from tools.delegate_tool_dispatch import DelegatedTask as DispatchTask

        dispatch_task = DispatchTask(
            task_id=task_id,
            task_type=task.task_type,
            command=command,
            params=task.params,
            config=task.config if isinstance(task.config, DelegateConfig) else None,
        )

        result = await dispatcher.dispatch(dispatch_task)

        if result.timed_out:
            task.status = "timeout"
            progress.fail(task_id, "Task timed out")
        elif result.exit_code != 0:
            task.status = "failed"
            progress.fail(task_id, f"Task failed with exit code {result.exit_code}")
        else:
            task.status = "completed"
            progress.complete(task_id, result={"exit_code": result.exit_code})

        task.result = result
        self._history.append(task)

        if self.storage_path:
            await self._persist_task(task)

        return result

    async def get_result(
        self,
        task_id: str,
        timeout: float = 0,
    ) -> Any:
        """Get the result of a task.

        Args:
            task_id: The task ID.
            timeout: Wait timeout in seconds (0 = don't wait).

        Returns:
            TaskResult or None if not found.
        """
        task = self.active_tasks.get(task_id)
        if not task:
            return None

        if task.status in ("completed", "failed", "timeout"):
            return task.result

        if timeout > 0 and task.status == "running":
            start_time = time.monotonic()
            while time.monotonic() - start_time < timeout:
                await asyncio.sleep(0.1)
                if task.status in ("completed", "failed", "timeout"):
                    return task.result

        return task.result

    def cancel(self, task_id: str) -> bool:
        """Cancel a running task.

        Args:
            task_id: The task ID to cancel.

        Returns:
            True if cancelled, False if not found or already completed.
        """
        task = self.active_tasks.get(task_id)
        if not task:
            return False

        if task.status in ("completed", "failed", "timeout", "cancelled"):
            return False

        dispatcher = self._get_dispatcher()
        cancelled = dispatcher.cancel(task_id)

        if cancelled:
            task.status = "cancelled"
            progress = self._get_progress_tracker()
            progress.cancel(task_id)
            self._history.append(task)
            logger.info("Cancelled task: %s", task_id)

        return cancelled

    def list_active(self) -> list[DelegatedTask]:
        """List all active tasks.

        Returns:
            List of active DelegatedTask objects.
        """
        return [task for task in self.active_tasks.values() if task.status in ("pending", "running")]

    def get_history(self, limit: int = 100) -> list[DelegatedTask]:
        """Get task execution history.

        Args:
            limit: Maximum number of history entries to return.

        Returns:
            List of completed/failed DelegatedTask objects.
        """
        return self._history[-limit:]

    async def replay(self, task_id: str) -> Any:
        """Replay a completed or failed task.

        Args:
            task_id: The task ID to replay.

        Returns:
            TaskResult from replay.
        """
        task = self.active_tasks.get(task_id)
        if not task:
            task = self._find_in_history(task_id)

        if not task:
            from tools.delegate_tool_child_run import TaskResult
            return TaskResult(
                task_id=task_id,
                exit_code=-1,
                stdout="",
                stderr="Task not found in active or history",
                duration=0.0,
                timed_out=False,
                memory_peak_mb=0.0,
            )

        task.status = "pending"
        task.result = None
        return await self.execute(task_id)

    def _find_in_history(self, task_id: str) -> DelegatedTask | None:
        """Find a task in history by ID."""
        for task in self._history:
            if task.task_id == task_id:
                return task
        return None

    async def _persist_task(self, task: DelegatedTask) -> None:
        """Persist task to storage.

        Args:
            task: The task to persist.
        """
        if not self.storage_path:
            return

        try:
            self.storage_path.mkdir(parents=True, exist_ok=True)
            file_path = self.storage_path / f"{task.task_id}.json"
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(task.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("Failed to persist task %s: %s", task.task_id, e)

    async def load_task(self, task_id: str) -> DelegatedTask | None:
        """Load a task from storage.

        Args:
            task_id: The task ID to load.

        Returns:
            DelegatedTask or None if not found.
        """
        if not self.storage_path:
            return None

        file_path = self.storage_path / f"{task_id}.json"
        if not file_path.exists():
            return None

        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
            return DelegatedTask.from_dict(data)
        except Exception as e:
            logger.error("Failed to load task %s: %s", task_id, e)
            return None

    def clear_completed(self) -> int:
        """Remove completed tasks from active tracking.

        Returns:
            Number of tasks cleared.
        """
        to_remove = [
            task_id
            for task_id, task in self.active_tasks.items()
            if task.status in ("completed", "failed", "timeout", "cancelled")
        ]
        for task_id in to_remove:
            del self.active_tasks[task_id]
        return len(to_remove)
