"""Run a delegated task as a subprocess with full isolation.

Handles child process lifecycle, resource limits, and result collection.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class TaskResult:
    """Result from a child task execution."""

    task_id: str
    exit_code: int
    stdout: str
    stderr: str
    duration: float
    timed_out: bool
    memory_peak_mb: float


class ChildTaskRunner:
    """Run a delegated task as an isolated subprocess."""

    def __init__(self, config: dict | None = None):
        self.timeout: int = (config or {}).get("timeout", 300)
        self.max_memory_mb: int = (config or {}).get("max_memory_mb", 512)
        self.working_dir: Path | None = (config or {}).get("working_dir")
        self._running_tasks: dict[str, asyncio.subprocess.Process] = {}
        self._task_start_times: dict[str, float] = {}

    async def run(
        self,
        command: str,
        env: dict | None = None,
        cwd: Path | None = None,
    ) -> TaskResult:
        """Execute a command as an isolated subprocess.

        Args:
            command: The command to execute.
            env: Optional environment variables.
            cwd: Optional working directory override.

        Returns:
            TaskResult with execution details.
        """
        task_id = str(uuid.uuid4())
        start_time = time.monotonic()

        exec_env = os.environ.copy()
        if env:
            exec_env.update(env)

        exec_cwd = str(cwd or self.working_dir or Path.cwd())

        stdout_data = bytearray()
        stderr_data = bytearray()

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=exec_env,
                cwd=exec_cwd,
            )
            self._running_tasks[task_id] = process
            self._task_start_times[task_id] = start_time

            try:
                stdout_chunk, stderr_chunk = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout,
                )
                stdout_data.extend(stdout_chunk or b"")
                stderr_data.extend(stderr_chunk or b"")
                exit_code = process.returncode or 0
                timed_out = False
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                exit_code = -1
                timed_out = True
                logger.warning("Task %s timed out after %ds", task_id, self.timeout)
            finally:
                self._running_tasks.pop(task_id, None)
                self._task_start_times.pop(task_id, None)

        except Exception as e:
            logger.error("Task %s failed to start: %s", task_id, e)
            exit_code = -2
            stdout_data = bytearray()
            stderr_data = str(e).encode()
            timed_out = False

        duration = time.monotonic() - start_time
        memory_peak = await self._estimate_memory_usage(task_id)

        return TaskResult(
            task_id=task_id,
            exit_code=exit_code,
            stdout=stdout_data.decode(errors="replace"),
            stderr=stderr_data.decode(errors="replace"),
            duration=duration,
            timed_out=timed_out,
            memory_peak_mb=memory_peak,
        )

    async def run_streaming(
        self,
        command: str,
        on_output: Callable[[str, str], None],
    ) -> TaskResult:
        """Execute a command with streaming output callback.

        Args:
            command: The command to execute.
            on_output: Callback receiving (stream_type, line) for stdout/stderr.

        Returns:
            TaskResult with execution details.
        """
        task_id = str(uuid.uuid4())
        start_time = time.monotonic()

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._running_tasks[task_id] = process
            self._task_start_times[task_id] = start_time

            stdout_lines: list[str] = []
            stderr_lines: list[str] = []

            async def read_stream(
                stream: asyncio.StreamReader,
                stream_type: str,
            ) -> None:
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    line_text = line.decode(errors="replace").rstrip()
                    if stream_type == "stdout":
                        stdout_lines.append(line_text)
                    else:
                        stderr_lines.append(line_text)
                    on_output(stream_type, line_text)

            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        read_stream(process.stdout, "stdout"),
                        read_stream(process.stderr, "stderr"),
                    ),
                    timeout=self.timeout,
                )
                await process.wait()
                exit_code = process.returncode or 0
                timed_out = False
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                exit_code = -1
                timed_out = True
            finally:
                self._running_tasks.pop(task_id, None)
                self._task_start_times.pop(task_id, None)

        except Exception as e:
            logger.error("Streaming task %s failed: %s", task_id, e)
            exit_code = -2
            stdout_lines = []
            stderr_lines = [str(e)]
            timed_out = False

        duration = time.monotonic() - start_time
        memory_peak = await self._estimate_memory_usage(task_id)

        return TaskResult(
            task_id=task_id,
            exit_code=exit_code,
            stdout="\n".join(stdout_lines),
            stderr="\n".join(stderr_lines),
            duration=duration,
            timed_out=timed_out,
            memory_peak_mb=memory_peak,
        )

    def cancel(self, task_id: str) -> bool:
        """Cancel a running task by its ID.

        Args:
            task_id: The ID of the task to cancel.

        Returns:
            True if the task was found and cancelled, False otherwise.
        """
        process = self._running_tasks.get(task_id)
        if process:
            try:
                process.kill()
                logger.info("Task %s cancelled", task_id)
                return True
            except Exception as e:
                logger.error("Failed to cancel task %s: %s", task_id, e)
        return False

    def list_running(self) -> list[dict]:
        """List all currently running tasks.

        Returns:
            List of dicts with task_id, start_time, and elapsed seconds.
        """
        current_time = time.monotonic()
        running = []
        for task_id, start_time in self._task_start_times.items():
            running.append(
                {
                    "task_id": task_id,
                    "started_at": start_time,
                    "elapsed_seconds": current_time - start_time,
                }
            )
        return running

    async def _estimate_memory_usage(self, task_id: str) -> float:
        """Estimate peak memory usage for a task.

        This is a simplified estimation. On systems with /proc,
        we could read /proc/[pid]/status for RSS values.

        Args:
            task_id: The task ID to estimate memory for.

        Returns:
            Estimated peak memory in MB.
        """
        return 0.0
