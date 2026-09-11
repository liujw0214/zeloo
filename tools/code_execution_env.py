"""Manage execution environments for code: venv, conda, docker, remote."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result of code execution."""

    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    duration: float = 0.0
    timed_out: bool = False
    error: str | None = None

    @property
    def output(self) -> str:
        """Combined output."""
        parts = []
        if self.stdout:
            parts.append(self.stdout)
        if self.stderr:
            parts.append(self.stderr)
        return "\n".join(parts) if parts else ""

    @property
    def success(self) -> bool:
        """Check if execution succeeded."""
        return self.returncode == 0 and not self.timed_out and self.error is None


class ExecutionEnvironment:
    """Abstract execution environment."""

    async def setup(self) -> bool:
        """Set up the execution environment."""
        raise NotImplementedError

    async def teardown(self) -> None:
        """Clean up the execution environment."""
        raise NotImplementedError

    async def run(self, code: str, timeout: float = 30) -> ExecutionResult:
        """Run code in the environment."""
        raise NotImplementedError

    async def install(self, package: str) -> bool:
        """Install a package in the environment."""
        raise NotImplementedError


class VirtualEnvEnvironment(ExecutionEnvironment):
    """Python virtualenv environment."""

    def __init__(
        self,
        venv_path: Path | str,
        python_version: str = "3.11",
        timeout: float = 30.0,
    ) -> None:
        self.venv_path = Path(venv_path)
        self.python_version = python_version
        self.timeout = timeout
        self._python_exe: Path | None = None
        self._setup_done: bool = False

    async def setup(self) -> bool:
        """Create and set up a Python virtual environment."""
        if self._setup_done:
            return True

        try:
            if self.venv_path.exists():
                shutil.rmtree(self.venv_path)

            self.venv_path.parent.mkdir(parents=True, exist_ok=True)

            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "venv",
                str(self.venv_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                logger.error("Failed to create venv: %s", stderr.decode())
                return False

            if sys.platform == "win32":
                self._python_exe = self.venv_path / "Scripts" / "python.exe"
            else:
                self._python_exe = self.venv_path / "bin" / "python"

            self._setup_done = True
            logger.info("VirtualEnv created at %s", self.venv_path)
            return True

        except Exception as e:
            logger.exception("Failed to setup VirtualEnv")
            self.error = f"Setup failed: {e}"
            return False

    async def teardown(self) -> None:
        """Remove the virtual environment."""
        try:
            if self.venv_path.exists():
                shutil.rmtree(self.venv_path)
                logger.info("VirtualEnv removed: %s", self.venv_path)
        except Exception as e:
            logger.warning("Failed to remove venv: %s", e)

    async def run(self, code: str, timeout: float = 30) -> ExecutionResult:
        """Execute Python code in the virtual environment."""
        if not self._setup_done:
            success = await self.setup()
            if not success:
                return ExecutionResult(
                    returncode=-1,
                    error=f"Environment setup failed: {getattr(self, 'error', 'Unknown error')}",
                )

        if self._python_exe is None:
            return ExecutionResult(returncode=-1, error="Python executable not found")

        start_time = asyncio.get_event_loop().time()
        tmp_file = self.venv_path / f"exec_{uuid.uuid4().hex[:8]}.py"

        try:
            tmp_file.write_text(code, encoding="utf-8")

            process = await asyncio.create_subprocess_exec(
                str(self._python_exe),
                str(tmp_file),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.venv_path),
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(), timeout=timeout
                )
                duration = asyncio.get_event_loop().time() - start_time

                return ExecutionResult(
                    stdout=stdout_bytes.decode("utf-8", errors="replace"),
                    stderr=stderr_bytes.decode("utf-8", errors="replace"),
                    returncode=process.returncode or 0,
                    duration=duration,
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                duration = asyncio.get_event_loop().time() - start_time
                return ExecutionResult(
                    returncode=-1,
                    timed_out=True,
                    error=f"Execution timed out after {timeout}s",
                    duration=duration,
                )

        except Exception as e:
            duration = asyncio.get_event_loop().time() - start_time
            return ExecutionResult(
                returncode=-1, error=f"Execution error: {e}", duration=duration
            )
        finally:
            if tmp_file.exists():
                try:
                    tmp_file.unlink()
                except Exception:
                    pass

    async def install(self, package: str) -> bool:
        """Install a package using pip."""
        if not self._setup_done:
            await self.setup()

        if self._python_exe is None:
            return False

        try:
            proc = await asyncio.create_subprocess_exec(
                str(self._python_exe),
                "-m",
                "pip",
                "install",
                package,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                logger.error("pip install failed: %s", stderr.decode())
                return False

            logger.info("Package installed: %s", package)
            return True

        except Exception as e:
            logger.exception("Failed to install package")
            return False


class DockerEnvironment(ExecutionEnvironment):
    """Docker container environment."""

    def __init__(
        self,
        image: str = "python:3.11-slim",
        name: str = "",
        timeout: float = 30.0,
    ) -> None:
        self.image = image
        self.container_name = name or f"zeloo-exec-{uuid.uuid4().hex[:8]}"
        self.timeout = timeout
        self._container_id: str | None = None
        self._setup_done: bool = False

    async def setup(self) -> bool:
        """Pull image and create container."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "pull",
                self.image,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()

            if proc.returncode != 0:
                logger.warning("Docker pull failed, continuing anyway")

            proc = await asyncio.create_subprocess_exec(
                "docker",
                "run",
                "-d",
                "--name",
                self.container_name,
                "--rm",
                self.image,
                "sleep",
                "3600",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                logger.error("Failed to create container: %s", stderr.decode())
                return False

            self._container_id = stdout.decode().strip()
            self._setup_done = True
            logger.info("Docker container created: %s", self.container_name)
            return True

        except FileNotFoundError:
            logger.error("Docker not found in PATH")
            return False
        except Exception as e:
            logger.exception("Docker setup failed")
            return False

    async def teardown(self) -> None:
        """Stop and remove the container."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "stop",
                self.container_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            logger.info("Docker container stopped: %s", self.container_name)
        except Exception as e:
            logger.warning("Failed to stop container: %s", e)

    async def run(self, code: str, timeout: float = 30) -> ExecutionResult:
        """Execute Python code inside the Docker container."""
        if not self._setup_done:
            success = await self.setup()
            if not success:
                return ExecutionResult(returncode=-1, error="Docker setup failed")

        start_time = asyncio.get_event_loop().time()
        encoded_code = base64.b64encode(code.encode()).decode()

        try:
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "exec",
                self.container_name,
                "python",
                "-c",
                f"import base64; exec(base64.b64decode('{encoded_code}').decode())",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
                duration = asyncio.get_event_loop().time() - start_time

                return ExecutionResult(
                    stdout=stdout.decode("utf-8", errors="replace"),
                    stderr=stderr.decode("utf-8", errors="replace"),
                    returncode=proc.returncode or 0,
                    duration=duration,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                duration = asyncio.get_event_loop().time() - start_time
                return ExecutionResult(
                    returncode=-1,
                    timed_out=True,
                    error=f"Execution timed out after {timeout}s",
                    duration=duration,
                )

        except Exception as e:
            duration = asyncio.get_event_loop().time() - start_time
            return ExecutionResult(
                returncode=-1, error=f"Execution error: {e}", duration=duration
            )

    async def install(self, package: str) -> bool:
        """Install a package using pip in the container."""
        if not self._setup_done:
            await self.setup()

        try:
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "exec",
                self.container_name,
                "pip",
                "install",
                package,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                logger.error("pip install failed: %s", stderr.decode())
                return False

            return True

        except Exception as e:
            logger.exception("Failed to install package in container")
            return False


class RemoteEnvironment(ExecutionEnvironment):
    """Remote execution via SSH."""

    def __init__(
        self,
        host: str,
        user: str,
        key_path: Path | str | None = None,
        password: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.host = host
        self.user = user
        self.key_path = Path(key_path) if key_path else None
        self.password = password
        self.timeout = timeout
        self._connected: bool = False

    async def setup(self) -> bool:
        """Test SSH connection to remote host."""
        cmd = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "BatchMode=yes"]

        if self.key_path:
            cmd.extend(["-i", str(self.key_path)])

        cmd.extend([f"{self.user}@{self.host}", "echo", "connected"])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                self._connected = True
                logger.info("SSH connection established: %s@%s", self.user, self.host)
                return True

            logger.error("SSH connection failed: %s", stderr.decode())
            return False

        except FileNotFoundError:
            logger.error("ssh command not found")
            return False
        except Exception as e:
            logger.exception("SSH setup failed")
            return False

    async def teardown(self) -> None:
        """Clean up remote session."""
        self._connected = False
        logger.info("Remote session ended")

    async def run(self, code: str, timeout: float = 30) -> ExecutionResult:
        """Execute Python code on remote host via SSH."""
        if not self._connected:
            success = await self.setup()
            if not success:
                return ExecutionResult(returncode=-1, error="SSH connection failed")

        start_time = asyncio.get_event_loop().time()
        encoded_code = base64.b64encode(code.encode()).decode()

        ssh_cmd = ["ssh", "-o", "StrictHostKeyChecking=no"]
        if self.key_path:
            ssh_cmd.extend(["-i", str(self.key_path)])

        remote_cmd = (
            f"python3 -c \"import base64; exec(base64.b64decode('{encoded_code}').decode())\""
        )
        ssh_cmd.extend([f"{self.user}@{self.host}", remote_cmd])

        try:
            proc = await asyncio.create_subprocess_exec(
                *ssh_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
                duration = asyncio.get_event_loop().time() - start_time

                return ExecutionResult(
                    stdout=stdout.decode("utf-8", errors="replace"),
                    stderr=stderr.decode("utf-8", errors="replace"),
                    returncode=proc.returncode or 0,
                    duration=duration,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                duration = asyncio.get_event_loop().time() - start_time
                return ExecutionResult(
                    returncode=-1,
                    timed_out=True,
                    error=f"Execution timed out after {timeout}s",
                    duration=duration,
                )

        except Exception as e:
            duration = asyncio.get_event_loop().time() - start_time
            return ExecutionResult(
                returncode=-1, error=f"Execution error: {e}", duration=duration
            )

    async def install(self, package: str) -> bool:
        """Install a package on remote host."""
        if not self._connected:
            await self.setup()

        ssh_cmd = ["ssh", "-o", "StrictHostKeyChecking=no"]
        if self.key_path:
            ssh_cmd.extend(["-i", str(self.key_path)])

        remote_cmd = f"pip3 install {package}"
        ssh_cmd.extend([f"{self.user}@{self.host}", remote_cmd])

        try:
            proc = await asyncio.create_subprocess_exec(
                *ssh_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                logger.error("Remote pip install failed: %s", stderr.decode())
                return False

            return True

        except Exception as e:
            logger.exception("Failed to install package remotely")
            return False


import base64
