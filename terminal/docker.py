"""Docker container terminal backend — executes commands inside a Docker container."""

from __future__ import annotations

import subprocess
import threading

from .base import CommandResult, TerminalBackend


class DockerTerminalBackend(TerminalBackend):
    """Execute commands inside a Docker container.

    Requires: Docker daemon running locally or via DOCKER_HOST.
    The container is kept alive between commands for efficiency.

    Example config::

        {
            "image": "python:3.11-slim",
            "container_name": "Zeloo-runtime",
            "workdir": "/app"
        }
    """

    name = "docker"

    def __init__(
        self,
        image: str = "python:3.11-slim",
        container_name: str = "",
        workdir: str = "/workspace",
        network: str = "bridge",
    ) -> None:
        self._image = image
        self._container_name = container_name or f"Zeloo-{image.replace(':', '-')}"
        self._workdir = workdir
        self._network = network
        self._container_id: str = ""
        self._lock = threading.Lock()
        try:
            self._ensure_container()
        except FileNotFoundError as exc:
            raise ImportError(
                "Docker not available. Install Docker or use 'local' backend. "
                f"Original error: {exc}"
            ) from exc

    def _ensure_container(self) -> None:
        result = subprocess.run(
            ["docker", "ps", "-a", "--filter", f"name={self._container_name}", "--format", "{{.ID}}"],
            capture_output=True,
            text=True,
        )
        container_id = result.stdout.strip()

        if container_id:
            subprocess.run(["docker", "rm", "-f", container_id], capture_output=True)

        subprocess.run(
            [
                "docker", "run", "-d",
                "--name", self._container_name,
                "-w", self._workdir,
                "--network", self._network,
                "--restart", "unless-stopped",
                self._image,
                "sleep", "infinity",
            ],
            check=True,
        )
        self._container_id = self._container_name

    def execute(self, command: str, timeout: int = 30) -> CommandResult:
        with self._lock:
            try:
                result = subprocess.run(
                    [
                        "docker", "exec",
                        "-w", self._workdir,
                        self._container_name,
                        "sh", "-c", command,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                return CommandResult(
                    stdout=result.stdout,
                    stderr=result.stderr,
                    returncode=result.returncode,
                    timed_out=False,
                )
            except subprocess.TimeoutExpired:
                return CommandResult(
                    stdout="",
                    stderr=f"Command timed out after {timeout}s",
                    returncode=124,
                    timed_out=True,
                )

    def put_file(self, content: bytes, dest: str) -> CommandResult:
        import base64
        import os
        import tempfile

        encoded = base64.b64encode(content).decode()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".sh") as f:
            f.write(f'echo "{encoded}" | base64 -d > {dest}'.encode())
            script_path = f.name

        try:
            subprocess.run(
                ["docker", "cp", script_path, f"{self._container_name}:/tmp/_put.sh"],
                capture_output=True,
                text=True,
            )
            os.unlink(script_path)
            return subprocess.run(
                ["docker", "exec", self._container_name, "sh", "/tmp/_put.sh"],
                capture_output=True,
                text=True,
            )
        finally:
            subprocess.run(
                ["docker", "exec", self._container_name, "rm", "-f", "/tmp/_put.sh"],
                capture_output=True,
            )

    def get_file(self, path: str) -> bytes:
        import subprocess
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False) as f:
            tmp = f.name
        try:
            subprocess.run(
                ["docker", "cp", f"{self._container_name}:{path}", tmp],
                check=True,
            )
            with open(tmp, "rb") as f:
                return f.read()
        finally:
            import os
            os.unlink(tmp)

    def close(self) -> None:
        subprocess.run(["docker", "rm", "-f", self._container_name], capture_output=True)


DockerBackend = DockerTerminalBackend
