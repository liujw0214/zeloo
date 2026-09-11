"""Track progress of delegated tasks in real-time."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class TaskProgress:
    """Progress information for a delegated task."""

    task_id: str
    status: str
    step: int
    total_steps: int
    message: str
    started_at: float
    updated_at: float
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert progress to dictionary.

        Returns:
            Dictionary representation.
        """
        return {
            "task_id": self.task_id,
            "status": self.status,
            "step": self.step,
            "total_steps": self.total_steps,
            "message": self.message,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "elapsed_seconds": time.monotonic() - self.started_at,
            "metadata": self.metadata,
        }

    @property
    def percent_complete(self) -> float:
        """Calculate percentage complete.

        Returns:
            Percentage from 0.0 to 100.0.
        """
        if self.total_steps <= 0:
            return 0.0
        return min(100.0, (self.step / self.total_steps) * 100.0)


class TaskProgressTracker:
    """Real-time progress tracking for delegated tasks."""

    def __init__(self):
        self.active_tasks: dict[str, TaskProgress] = {}
        self.listeners: list[Callable[[TaskProgress], None]] = []

    def start_tracking(self, task_id: str, total_steps: int = 0) -> TaskProgress:
        """Start tracking a new task.

        Args:
            task_id: Unique identifier for the task.
            total_steps: Total number of steps expected (0 for unknown).

        Returns:
            The created TaskProgress object.
        """
        current_time = time.monotonic()
        progress = TaskProgress(
            task_id=task_id,
            status="running",
            step=0,
            total_steps=total_steps,
            message="Task started",
            started_at=current_time,
            updated_at=current_time,
            metadata={},
        )
        self.active_tasks[task_id] = progress
        self._notify_listeners(progress)
        logger.debug("Started tracking task: %s", task_id)
        return progress

    def update(
        self,
        task_id: str,
        step: int,
        message: str = "",
        metadata: dict | None = None,
    ) -> TaskProgress | None:
        """Update progress for a tracked task.

        Args:
            task_id: The task to update.
            step: Current step number.
            message: Optional progress message.
            metadata: Optional additional metadata.

        Returns:
            Updated TaskProgress or None if task not found.
        """
        progress = self.active_tasks.get(task_id)
        if not progress:
            logger.warning("Attempted to update non-existent task: %s", task_id)
            return None

        progress.step = step
        if message:
            progress.message = message
        if metadata:
            progress.metadata.update(metadata)
        progress.updated_at = time.monotonic()

        self._notify_listeners(progress)
        logger.debug(
            "Task %s progress: step %d/%d - %s",
            task_id,
            step,
            progress.total_steps,
            message or "",
        )
        return progress

    def increment(self, task_id: str, message: str = "", metadata: dict | None = None) -> TaskProgress | None:
        """Increment step counter by 1.

        Args:
            task_id: The task to increment.
            message: Optional progress message.
            metadata: Optional additional metadata.

        Returns:
            Updated TaskProgress or None if task not found.
        """
        progress = self.active_tasks.get(task_id)
        if not progress:
            return None
        return self.update(
            task_id,
            progress.step + 1,
            message=message,
            metadata=metadata,
        )

    def complete(self, task_id: str, result: dict | None = None) -> TaskProgress | None:
        """Mark a task as completed.

        Args:
            task_id: The task to complete.
            result: Optional result data to store.

        Returns:
            Updated TaskProgress or None if task not found.
        """
        progress = self.active_tasks.get(task_id)
        if not progress:
            logger.warning("Attempted to complete non-existent task: %s", task_id)
            return None

        progress.status = "completed"
        progress.updated_at = time.monotonic()
        if result:
            progress.metadata["result"] = result

        self._notify_listeners(progress)
        logger.info("Task %s completed successfully", task_id)
        return progress

    def fail(self, task_id: str, error: str) -> TaskProgress | None:
        """Mark a task as failed.

        Args:
            task_id: The task that failed.
            error: Error message or details.

        Returns:
            Updated TaskProgress or None if task not found.
        """
        progress = self.active_tasks.get(task_id)
        if not progress:
            logger.warning("Attempted to fail non-existent task: %s", task_id)
            return None

        progress.status = "failed"
        progress.updated_at = time.monotonic()
        progress.metadata["error"] = error

        self._notify_listeners(progress)
        logger.error("Task %s failed: %s", task_id, error)
        return progress

    def cancel(self, task_id: str) -> TaskProgress | None:
        """Mark a task as cancelled.

        Args:
            task_id: The task to cancel.

        Returns:
            Updated TaskProgress or None if task not found.
        """
        progress = self.active_tasks.get(task_id)
        if not progress:
            return None

        progress.status = "cancelled"
        progress.updated_at = time.monotonic()

        self._notify_listeners(progress)
        logger.info("Task %s cancelled", task_id)
        return progress

    def subscribe(self, listener: Callable[[TaskProgress], None]) -> None:
        """Subscribe to progress updates.

        Args:
            listener: Callback function to receive updates.
        """
        if listener not in self.listeners:
            self.listeners.append(listener)
            logger.debug("New progress listener registered")

    def unsubscribe(self, listener: Callable[[TaskProgress], None]) -> bool:
        """Unsubscribe from progress updates.

        Args:
            listener: The callback to remove.

        Returns:
            True if removed, False if not found.
        """
        if listener in self.listeners:
            self.listeners.remove(listener)
            return True
        return False

    def get_progress(self, task_id: str) -> TaskProgress | None:
        """Get current progress for a task.

        Args:
            task_id: The task ID to look up.

        Returns:
            TaskProgress or None if not found.
        """
        return self.active_tasks.get(task_id)

    def get_all_active(self) -> list[TaskProgress]:
        """Get all active task progress.

        Returns:
            List of all tracked task progress objects.
        """
        return list(self.active_tasks.values())

    def clear(self) -> None:
        """Clear all tracked tasks."""
        self.active_tasks.clear()
        logger.debug("Cleared all task progress tracking")

    def cleanup_completed(self, max_age_seconds: float = 3600) -> int:
        """Remove old completed/failed tasks.

        Args:
            max_age_seconds: Remove tasks older than this.

        Returns:
            Number of tasks removed.
        """
        current_time = time.monotonic()
        to_remove: list[str] = []

        for task_id, progress in self.active_tasks.items():
            if progress.status in ("completed", "failed", "cancelled"):
                if current_time - progress.updated_at > max_age_seconds:
                    to_remove.append(task_id)

        for task_id in to_remove:
            del self.active_tasks[task_id]

        if to_remove:
            logger.debug("Cleaned up %d completed tasks", len(to_remove))

        return len(to_remove)

    def _notify_listeners(self, progress: TaskProgress) -> None:
        """Notify all listeners of a progress update.

        Args:
            progress: The updated progress object.
        """
        for listener in self.listeners:
            try:
                listener(progress)
            except Exception as e:
                logger.error("Progress listener error: %s", e)
