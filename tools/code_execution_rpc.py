"""RPC bridge for code execution: run code on remote server, return result."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class RPCResult:
    """Result of an RPC call."""

    success: bool = False
    execution_id: str = ""
    output: str = ""
    error: str | None = None
    status: str = "pending"
    duration: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def stdout(self) -> str:
        """Alias for output."""
        return self.output

    @property
    def stderr(self) -> str:
        """Get stderr from metadata if available."""
        return self.metadata.get("stderr", "")


class CodeExecutionRPC:
    """RPC client for remote code execution."""

    def __init__(
        self,
        server_url: str,
        api_key: str = "",
        timeout: float = 30.0,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._session: Any = None

    async def _get_session(self) -> Any:
        """Get or create httpx async client."""
        try:
            import httpx

            if self._session is None:
                self._session = httpx.AsyncClient(timeout=self.timeout)
            return self._session
        except ImportError:
            raise RuntimeError("httpx is required for RPC calls. Install with: pip install httpx")

    async def _request(
        self,
        method: str,
        endpoint: str,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an HTTP request to the RPC server."""
        session = await self._get_session()
        url = f"{self.server_url}/{endpoint.lstrip('/')}"

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            if method.upper() == "GET":
                response = await session.get(url, headers=headers, params=params)
            elif method.upper() == "POST":
                response = await session.post(url, headers=headers, json=data)
            elif method.upper() == "DELETE":
                response = await session.delete(url, headers=headers)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as e:
            logger.error("HTTP error %d: %s", e.response.status_code, e.response.text)
            return {
                "success": False,
                "error": f"HTTP {e.response.status_code}: {e.response.text}",
            }
        except httpx.RequestError as e:
            logger.error("Request error: %s", e)
            return {"success": False, "error": f"Request error: {e}"}
        except Exception as e:
            logger.exception("Unexpected error")
            return {"success": False, "error": str(e)}

    async def execute(
        self,
        code: str,
        language: str = "python",
        timeout: float = 30,
    ) -> RPCResult:
        """Execute code on the remote server.

        Args:
            code: The source code to execute.
            language: Programming language (python, javascript, etc.).
            timeout: Maximum execution time in seconds.

        Returns:
            RPCResult containing execution output and status.
        """
        execution_id = uuid.uuid4().hex

        payload = {
            "code": code,
            "language": language,
            "timeout": timeout,
            "execution_id": execution_id,
        }

        result = await self._request("POST", "/execute", data=payload)

        if not result:
            return RPCResult(
                success=False,
                execution_id=execution_id,
                error="No response from server",
            )

        return RPCResult(
            success=result.get("success", False),
            execution_id=result.get("execution_id", execution_id),
            output=result.get("output", ""),
            error=result.get("error"),
            status=result.get("status", "completed"),
            duration=result.get("duration", 0.0),
            metadata=result.get("metadata", {}),
        )

    async def execute_streaming(
        self,
        code: str,
        language: str = "python",
        on_output: Callable[[str], None] | None = None,
        timeout: float = 30,
    ) -> RPCResult:
        """Execute code with streaming output.

        Args:
            code: The source code to execute.
            language: Programming language.
            on_output: Callback function for each output chunk.
            timeout: Maximum execution time.

        Returns:
            RPCResult with accumulated output.
        """
        execution_id = uuid.uuid4().hex
        accumulated_output = []

        try:
            import httpx

            session = await self._get_session()
            url = f"{self.server_url}/execute/stream"

            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            payload = {
                "code": code,
                "language": language,
                "timeout": timeout,
                "execution_id": execution_id,
            }

            async with session.stream("POST", url, headers=headers, json=payload) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if not line:
                        continue

                    if line.startswith("data:"):
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break

                        try:
                            import json as json_module

                            parsed = json_module.loads(data)
                            chunk = parsed.get("output", "")
                            if chunk:
                                accumulated_output.append(chunk)
                                if on_output:
                                    on_output(chunk)
                        except Exception:
                            accumulated_output.append(data)
                            if on_output:
                                on_output(data)

            full_output = "".join(accumulated_output)
            return RPCResult(
                success=True,
                execution_id=execution_id,
                output=full_output,
                status="completed",
            )

        except httpx.HTTPStatusError as e:
            return RPCResult(
                success=False,
                execution_id=execution_id,
                error=f"HTTP {e.response.status_code}: {e.response.text}",
            )
        except Exception as e:
            logger.exception("Streaming execution failed")
            return RPCResult(
                success=False,
                execution_id=execution_id,
                error=f"Streaming error: {e}",
            )

    async def get_status(self, execution_id: str) -> dict[str, Any]:
        """Get the status of an execution.

        Args:
            execution_id: The ID of the execution to check.

        Returns:
            Dict containing execution status and results if complete.
        """
        result = await self._request("GET", f"/status/{execution_id}")
        return result

    async def cancel(self, execution_id: str) -> bool:
        """Cancel a running execution.

        Args:
            execution_id: The ID of the execution to cancel.

        Returns:
            True if cancellation was successful.
        """
        result = await self._request("DELETE", f"/execute/{execution_id}")
        return result.get("success", False)

    async def health_check(self) -> bool:
        """Check if the RPC server is healthy.

        Returns:
            True if the server is responding correctly.
        """
        result = await self._request("GET", "/health")

        if not result:
            return False

        return result.get("status") == "ok" or result.get("healthy", False)

    async def list_executions(self, limit: int = 10) -> list[dict[str, Any]]:
        """List recent executions.

        Args:
            limit: Maximum number of executions to return.

        Returns:
            List of execution records.
        """
        result = await self._request("GET", "/executions", params={"limit": limit})
        return result.get("executions", [])

    async def close(self) -> None:
        """Close the RPC client session."""
        if self._session:
            await self._session.aclose()
            self._session = None

    async def __aenter__(self) -> "CodeExecutionRPC":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.close()


class RPCServerSimulator:
    """Simulates an RPC server for testing purposes."""

    def __init__(self) -> None:
        self._executions: dict[str, dict[str, Any]] = {}
        self._health: bool = True

    async def handle_execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle execute request."""
        import asyncio
        import time

        execution_id = payload.get("execution_id", uuid.uuid4().hex)
        code = payload.get("code", "")
        timeout = payload.get("timeout", 30)

        self._executions[execution_id] = {
            "execution_id": execution_id,
            "status": "running",
            "start_time": time.time(),
        }

        try:
            await asyncio.sleep(0.1)

            output = f"Simulated output for: {code[:50]}..."
            error = None
            if "error" in code.lower():
                error = "Simulated error"

            duration = time.time() - self._executions[execution_id]["start_time"]
            self._executions[execution_id].update(
                {
                    "status": "completed",
                    "success": error is None,
                    "output": output,
                    "error": error,
                    "duration": duration,
                }
            )

            return {
                "success": error is None,
                "execution_id": execution_id,
                "output": output,
                "error": error,
                "status": "completed",
                "duration": duration,
            }

        except Exception as e:
            return {
                "success": False,
                "execution_id": execution_id,
                "error": str(e),
                "status": "failed",
            }

    async def handle_status(self, execution_id: str) -> dict[str, Any]:
        """Handle status request."""
        return self._executions.get(execution_id, {"status": "not_found"})

    async def handle_cancel(self, execution_id: str) -> dict[str, Any]:
        """Handle cancel request."""
        if execution_id in self._executions:
            self._executions[execution_id]["status"] = "cancelled"
            return {"success": True}
        return {"success": False, "error": "Execution not found"}

    async def handle_health(self) -> dict[str, Any]:
        """Handle health check."""
        return {"status": "ok", "healthy": self._health}

    async def handle_stream(
        self,
        payload: dict[str, Any],
        on_chunk: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        """Handle streaming execute request."""
        execution_id = payload.get("execution_id", uuid.uuid4().hex)
        code = payload.get("code", "")

        for i in range(3):
            chunk = f"chunk_{i}: {code[:20]}...\n"
            if on_chunk:
                on_chunk(chunk)
            await asyncio.sleep(0.05)

        return {
            "success": True,
            "execution_id": execution_id,
            "output": f"Complete simulated output for: {code}",
            "status": "completed",
        }


import httpx
import json
import time
import uuid
