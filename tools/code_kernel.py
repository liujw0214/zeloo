"""Jupyter-like code kernel: execute code with stateful namespace.

Supports Python and other languages via kernel adapters.
"""

from __future__ import annotations

import asyncio
import builtins
import code
import io
import logging
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from tools.code_execution_env import (
    DockerEnvironment,
    ExecutionEnvironment,
    ExecutionResult,
    VirtualEnvEnvironment,
)

logger = logging.getLogger(__name__)


@dataclass
class KernelResult:
    """Result of kernel code execution."""

    execution_count: int = 0
    status: str = "ok"
    output: str = ""
    error: str | None = None
    display_data: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        """Check if execution was successful."""
        return self.status == "ok" and self.error is None

    @property
    def stdout(self) -> str:
        """Alias for output."""
        return self.output


class PythonKernelAdapter:
    """Kernel adapter for Python code execution with stateful namespace."""

    def __init__(self, namespace: dict[str, Any] | None = None) -> None:
        self.namespace = namespace if namespace is not None else {}
        self._setup_default_imports()

    def _setup_default_imports(self) -> None:
        """Set up default imports in namespace."""
        self.namespace.setdefault("__builtins__", builtins.__dict__)

    def execute(self, code: str) -> tuple[str, str | None, str]:
        """Execute Python code.

        Args:
            code: Python source code.

        Returns:
            Tuple of (output, error, status).
        """
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()

        try:
            compiled = compile(code, "<kernel>", "exec", flags=0, dont_inherit=True)
            exec(compiled, self.namespace)

            stdout_output = sys.stdout.getvalue()
            stderr_output = sys.stderr.getvalue()
            sys.stdout = old_stdout
            sys.stderr = old_stderr

            return stdout_output, stderr_output if stderr_output else None, "ok"

        except SystemExit:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            return "", "SystemExit called", "error"

        except SyntaxError as e:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            error_msg = f"SyntaxError: {e.msg} at line {e.lineno}: {e.text}"
            return "", error_msg, "error"

        except Exception as e:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            import traceback

            tb = traceback.format_exc()
            error_msg = f"{type(e).__name__}: {e}\n{tb}"
            return "", error_msg, "error"

    def complete(self, code: str, cursor_pos: int) -> list[str]:
        """Get completion suggestions for code at cursor position.

        Args:
            code: Partial code.
            cursor_pos: Cursor position in code.

        Returns:
            List of completion candidates.
        """
        suggestions: list[str] = []

        try:
            import ast

            line = code[:cursor_pos].split("\n")[-1]
            parts = line.split(".")
            token = parts[-1].split()[-1] if parts else ""

            if len(parts) == 1:
                for name in dir(builtins):
                    if name.startswith(token):
                        suggestions.append(name)

                for name in self.namespace:
                    if name.startswith(token) and not name.startswith("__"):
                        suggestions.append(name)

            else:
                obj_name = parts[0]
                obj = self.namespace.get(obj_name)
                if obj is not None:
                    for name in dir(obj):
                        if name.startswith(token):
                            suggestions.append(name)

        except Exception as e:
            logger.debug("Completion error: %s", e)

        return suggestions[:20]

    def inspect(self, object_name: str) -> dict[str, Any] | None:
        """Inspect an object in the namespace.

        Args:
            object_name: Name of the object to inspect.

        Returns:
            Dict with object information or None.
        """
        obj = self.namespace.get(object_name)
        if obj is None:
            obj = getattr(builtins, object_name, None)

        if obj is None:
            return None

        result: dict[str, Any] = {
            "name": object_name,
            "type": type(obj).__name__,
        }

        try:
            result["doc"] = obj.__doc__ if hasattr(obj, "__doc__") else None
        except Exception:
            pass

        try:
            if callable(obj):
                result["callable"] = True
                import inspect

                sig = inspect.signature(obj)
                result["signature"] = str(sig)
        except Exception:
            pass

        return result


class CodeKernel:
    """Stateful code execution kernel."""

    def __init__(
        self,
        language: str = "python",
        env: ExecutionEnvironment | None = None,
        namespace: dict[str, Any] | None = None,
    ) -> None:
        self.language = language
        self.namespace: dict[str, Any] = namespace if namespace is not None else {}
        self.execution_count: int = 0
        self.env = env
        self._adapter: PythonKernelAdapter | None = None
        self._started: bool = False
        self._interrupt_event: asyncio.Event = asyncio.Event()

    async def start(self) -> bool:
        """Start the kernel and set up execution environment.

        Returns:
            True if kernel started successfully.
        """
        if self._started:
            return True

        try:
            if self.env:
                success = await self.env.setup()
                if not success:
                    logger.error("Failed to set up execution environment")
                    return False

            if self.language == "python":
                self._adapter = PythonKernelAdapter(self.namespace)
                self._setup_ipython_display()

            self._started = True
            logger.info("Kernel started: %s", self.language)
            return True

        except Exception as e:
            logger.exception("Failed to start kernel")
            return False

    def _setup_ipython_display(self) -> None:
        """Set up IPython-style display hooks."""
        display_callback: Callable[[str], None] | None = None

        def _display(data: dict[str, Any]) -> None:
            if self._adapter and hasattr(self, "_display_data"):
                self._display_data.append(data)

        self.namespace["display"] = _display

        if "display_data" not in self.namespace:
            self.namespace["display_data"] = []

    async def execute(self, code: str) -> KernelResult:
        """Execute code in the kernel.

        Args:
            code: Source code to execute.

        Returns:
            KernelResult with execution output.
        """
        if not self._started:
            success = await self.start()
            if not success:
                return KernelResult(
                    status="error",
                    error="Failed to start kernel",
                )

        self.execution_count += 1
        current_count = self.execution_count
        self._interrupt_event.clear()

        if self._adapter is None:
            return KernelResult(
                execution_count=current_count,
                status="error",
                error=f"No adapter for language: {self.language}",
            )

        if self._interrupt_event.is_set():
            return KernelResult(
                execution_count=current_count,
                status="abort",
                error="Execution aborted",
            )

        if self.env:
            result = await self.env.run(code)
            if result.error:
                return KernelResult(
                    execution_count=current_count,
                    status="error",
                    error=result.error,
                    output=result.stdout,
                )
            return KernelResult(
                execution_count=current_count,
                status="ok" if result.success else "error",
                output=result.stdout,
                error=result.stderr if result.stderr and not result.success else None,
            )

        loop = asyncio.get_event_loop()
        output, error, status = await loop.run_in_executor(None, self._adapter.execute, code)

        if self._interrupt_event.is_set():
            return KernelResult(
                execution_count=current_count,
                status="abort",
                error="Execution aborted",
                output=output,
            )

        return KernelResult(
            execution_count=current_count,
            status=status,
            output=output,
            error=error,
        )

    async def complete(self, code: str, cursor_pos: int) -> list[str]:
        """Get completion suggestions.

        Args:
            code: Partial code.
            cursor_pos: Cursor position.

        Returns:
            List of completion suggestions.
        """
        if self._adapter is None:
            return []

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._adapter.complete, code, cursor_pos
        )

    async def inspect(self, object_name: str) -> dict[str, Any] | None:
        """Inspect an object in the kernel namespace.

        Args:
            object_name: Name of object to inspect.

        Returns:
            Object information dict or None.
        """
        if self._adapter is None:
            return None

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._adapter.inspect, object_name)

    async def interrupt(self) -> None:
        """Interrupt the currently running execution."""
        self._interrupt_event.set()
        logger.info("Kernel execution interrupted")

    async def restart(self) -> None:
        """Restart the kernel, clearing the namespace."""
        await self.shutdown()

        if self.env:
            await self.env.teardown()

        self.namespace = {}
        self.execution_count = 0
        self._started = False

        await self.start()
        logger.info("Kernel restarted")

    async def shutdown(self) -> None:
        """Shutdown the kernel gracefully."""
        self._interrupt_event.set()

        if self.env:
            await self.env.teardown()

        self._started = False
        self._adapter = None
        logger.info("Kernel shut down")

    def get_namespace(self) -> dict[str, Any]:
        """Get the current kernel namespace.

        Returns:
            Copy of the namespace dictionary.
        """
        return dict(self.namespace)

    def set_namespace_value(self, name: str, value: Any) -> None:
        """Set a value in the kernel namespace.

        Args:
            name: Variable name.
            value: Value to set.
        """
        self.namespace[name] = value

    def get_namespace_value(self, name: str) -> Any:
        """Get a value from the kernel namespace.

        Args:
            name: Variable name.

        Returns:
            The value or None if not found.
        """
        return self.namespace.get(name)


class KernelManager:
    """Manages multiple kernel instances."""

    def __init__(self) -> None:
        self._kernels: dict[str, CodeKernel] = {}
        self._default_kernel: CodeKernel | None = None

    def create_kernel(
        self,
        kernel_id: str | None = None,
        language: str = "python",
        env: ExecutionEnvironment | None = None,
    ) -> tuple[str, CodeKernel]:
        """Create a new kernel.

        Args:
            kernel_id: Optional custom kernel ID.
            language: Programming language.
            env: Execution environment.

        Returns:
            Tuple of (kernel_id, kernel instance).
        """
        kid = kernel_id or uuid.uuid4().hex
        kernel = CodeKernel(language=language, env=env)
        self._kernels[kid] = kernel

        if self._default_kernel is None:
            self._default_kernel = kernel

        return kid, kernel

    def get_kernel(self, kernel_id: str) -> CodeKernel | None:
        """Get a kernel by ID.

        Args:
            kernel_id: Kernel identifier.

        Returns:
            Kernel instance or None.
        """
        return self._kernels.get(kernel_id)

    def get_default_kernel(self) -> CodeKernel | None:
        """Get the default kernel.

        Returns:
            Default kernel instance or None.
        """
        return self._default_kernel

    async def shutdown_all(self) -> None:
        """Shutdown all managed kernels."""
        for kernel in self._kernels.values():
            await kernel.shutdown()

        self._kernels.clear()
        self._default_kernel = None

    def remove_kernel(self, kernel_id: str) -> bool:
        """Remove a kernel.

        Args:
            kernel_id: Kernel identifier.

        Returns:
            True if kernel was removed.
        """
        if kernel_id in self._kernels:
            del self._kernels[kernel_id]
            return True
        return False
