"""Modal cloud terminal backend — executes commands via Modal app.

https://modal.com
"""

from __future__ import annotations

from typing import Any

from .base import CommandResult, TerminalBackend


class ModalTerminalBackend(TerminalBackend):
    """Execute commands on Modal cloud infrastructure.

    Provides serverless GPU/CPU compute with persistent containers.
    Requires: modal (pip install modal)

    Usage::

        from terminal.modal import ModalTerminalBackend
        backend = ModalTerminalBackend(app_name="Zeloo-runtime")
        result = backend.execute("python train.py --epochs 100")
    """

    name = "modal"

    def __init__(
        self,
        app_name: str = "Zeloo-runtime",
        image_tag: str = "python:3.11",
        gpu: str = "",
    ) -> None:
        self._app_name = app_name
        self._image_tag = image_tag
        self._gpu = gpu

    def execute(self, command: str, timeout: int = 300) -> CommandResult:
        try:
            import modal
        except ImportError:
            return CommandResult(
                stdout="",
                stderr="Modal SDK not installed. Run: pip install modal",
                returncode=1,
            )

        app = modal.App(self._app_name)
        secret = modal.Secret.from_name("Zeloo-secrets", deserialize=True)

        @app.function(
            image=modal.Image.debian_slim().pip_install("uv"),
            secrets=[secret],
            timeout=timeout,
        )
        def _run(command: str) -> dict[str, Any]:
            import shlex
            import subprocess

            proc = subprocess.run(
                shlex.split(command),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return {
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "returncode": proc.returncode,
            }

        output = _run.remote(command)
        return CommandResult(
            stdout=output["stdout"],
            stderr=output["stderr"],
            returncode=output["returncode"],
            timed_out=output.get("timed_out", False),
        )
