"""Dispatch delegated tasks to appropriate runners based on task type."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tools.delegate_tool_child_run import ChildTaskRunner, TaskResult
    from tools.delegate_tool_config import DelegateConfig

logger = logging.getLogger(__name__)


@dataclass
class DelegatedTask:
    """A task to be dispatched for execution."""

    task_id: str
    task_type: str
    command: str
    params: dict[str, Any] = field(default_factory=dict)
    config: DelegateConfig | None = None


class TaskDispatcher:
    """Route delegated tasks to the right executor."""

    def __init__(self):
        self.runners: dict[str, type] = {}
        self.default_runner: type = ChildTaskRunner
        self._active_tasks: dict[str, asyncio.Task] = {}

    def register(self, task_type: str, runner_class: type) -> None:
        """Register a runner class for a specific task type.

        Args:
            task_type: The type of task this runner handles.
            runner_class: The runner class to use for this task type.
        """
        self.runners[task_type] = runner_class
        logger.info("Registered runner %s for task type: %s", runner_class.__name__, task_type)

    def unregister(self, task_type: str) -> bool:
        """Unregister a runner for a task type.

        Args:
            task_type: The task type to unregister.

        Returns:
            True if unregistered, False if not found.
        """
        if task_type in self.runners:
            del self.runners[task_type]
            return True
        return False

    def _get_runner_class(self, task_type: str) -> type:
        """Get the runner class for a task type.

        Args:
            task_type: The task type to get runner for.

        Returns:
            Runner class to use.
        """
        return self.runners.get(task_type, self.default_runner)

    def _create_runner(self, runner_class: type, config: DelegateConfig | None) -> Any:
        """Create an instance of a runner class.

        Args:
            runner_class: The runner class to instantiate.
            config: Optional configuration for the runner.

        Returns:
            Runner instance.
        """
        if config:
            runner_config = config.to_dict()
            return runner_class(runner_config)
        return runner_class()

    async def dispatch(self, task: DelegatedTask) -> TaskResult:
        """Dispatch a single task for execution.

        Args:
            task: The task to dispatch.

        Returns:
            TaskResult from execution.
        """
        from tools.delegate_tool_child_run import ChildTaskRunner, TaskResult

        runner_class = self._get_runner_class(task.task_type)
        runner = self._create_runner(runner_class, task.config)

        if not hasattr(runner, "run"):
            error_result = TaskResult(
                task_id=task.task_id,
                exit_code=-1,
                stdout="",
                stderr=f"Runner {runner_class.__name__} does not implement run() method",
                duration=0.0,
                timed_out=False,
                memory_peak_mb=0.0,
            )
            return error_result

        env = None
        cwd = None
        if task.config:
            env = task.config.environment
            cwd = task.config.working_dir

        try:
            result = await runner.run(
                command=task.command,
                env=env,
                cwd=cwd,
            )
            logger.info(
                "Task %s (%s) completed with exit code %d",
                task.task_id,
                task.task_type,
                result.exit_code,
            )
            return result
        except Exception as e:
            logger.error("Task %s dispatch failed: %s", task.task_id, e)
            return TaskResult(
                task_id=task.task_id,
                exit_code=-2,
                stdout="",
                stderr=str(e),
                duration=0.0,
                timed_out=False,
                memory_peak_mb=0.0,
            )

    async def dispatch_streaming(
        self,
        task: DelegatedTask,
        on_output: Any,
    ) -> TaskResult:
        """Dispatch a task with streaming output.

        Args:
            task: The task to dispatch.
            on_output: Callback for streaming output.

        Returns:
            TaskResult from execution.
        """
        from tools.delegate_tool_child_run import ChildTaskRunner, TaskResult

        runner_class = self._get_runner_class(task.task_type)
        runner = self._create_runner(runner_class, task.config)

        if not hasattr(runner, "run_streaming"):
            return await self.dispatch(task)

        try:
            result = await runner.run_streaming(
                command=task.command,
                on_output=on_output,
            )
            return result
        except Exception as e:
            logger.error("Streaming task %s dispatch failed: %s", task.task_id, e)
            return TaskResult(
                task_id=task.task_id,
                exit_code=-2,
                stdout="",
                stderr=str(e),
                duration=0.0,
                timed_out=False,
                memory_peak_mb=0.0,
            )

    async def dispatch_batch(self, tasks: list[DelegatedTask]) -> list[TaskResult]:
        """Dispatch multiple tasks for parallel execution.

        Args:
            tasks: List of tasks to dispatch.

        Returns:
            List of TaskResults in the same order as input tasks.
        """
        from tools.delegate_tool_child_run import TaskResult

        if not tasks:
            return []

        async def dispatch_with_id(task: DelegatedTask) -> tuple[str, TaskResult]:
            result = await self.dispatch(task)
            return (task.task_id, result)

        results_map: dict[str, TaskResult] = {}
        results: list[TaskResult] = []

        dispatch_tasks = [dispatch_with_id(task) for task in tasks]
        completed = await asyncio.gather(*dispatch_tasks, return_exceptions=True)

        for i, item in enumerate(completed):
            if isinstance(item, Exception):
                results.append(
                    TaskResult(
                        task_id=tasks[i].task_id,
                        exit_code=-3,
                        stdout="",
                        stderr=f"Batch dispatch error: {item}",
                        duration=0.0,
                        timed_out=False,
                        memory_peak_mb=0.0,
                    )
                )
            else:
                task_id, result = item
                results_map[task_id] = result

        for task in tasks:
            if task.task_id in results_map:
                results.append(results_map[task.task_id])
            else:
                results.append(
                    TaskResult(
                        task_id=task.task_id,
                        exit_code=-4,
                        stdout="",
                        stderr="Task did not complete",
                        duration=0.0,
                        timed_out=False,
                        memory_peak_mb=0.0,
                    )
                )

        return results

    def cancel(self, task_id: str) -> bool:
        """Cancel a running task.

        Args:
            task_id: The ID of the task to cancel.

        Returns:
            True if cancelled, False if not found.
        """
        async_task = self._active_tasks.get(task_id)
        if async_task and not async_task.done():
            async_task.cancel()
            logger.info("Cancelled task: %s", task_id)
            return True
        return False

    def list_active(self) -> list[str]:
        """List IDs of active tasks.

        Returns:
            List of active task IDs.
        """
        return list(self._active_tasks.keys())
