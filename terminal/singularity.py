"""Singularity/Apptainer HPC terminal backend — executes commands in HPC environments."""

from __future__ import annotations

import subprocess
import threading

from .base import CommandResult, TerminalBackend


class SingularityTerminalBackend(TerminalBackend):
    """Execute commands inside a Singularity/Apptainer container on HPC systems.

    Suitable for academic and scientific computing environments where
    GPU/TPU clusters are managed via Singularity/Apptainer containers.
    Requires: singularity or apptainer CLI.

    Usage::

        backend = SingularityTerminalBackend(
            image="/path/to/gpu-image.sif",
            bind_paths=["/project", "/scratch"],
        )
        result = backend.execute("python train.py --epochs 200")
    """

    name = "singularity"

    def __init__(
        self,
        image: str = "",
        bind_paths: list[str] | None = None,
        env_vars: dict[str, str] | None = None,
        home_dir: str = "/home/user",
    ) -> None:
        self._image = image
        self._bind_paths = bind_paths or []
        self._env_vars = env_vars or {}
        self._home_dir = home_dir
        self._lock = threading.Lock()
        self._singularity_cmd = self._detect_singularity()

    def _detect_singularity(self) -> str:
        for cmd in ["singularity", "apptainer"]:
            result = subprocess.run(
                ["which", cmd], capture_output=True, text=True
            )
            if result.returncode == 0:
                return cmd
        return "singularity"

    def _build_args(self) -> list[str]:
        args = ["exec"]
        for bind in self._bind_paths:
            args.extend(["--bind", bind])
        for k, v in self._env_vars.items():
            args.extend(["--env", f"{k}={v}"])
        args.extend(["--home", self._home_dir])
        if self._image.endswith(".sif"):
            args.append("--nv")
        args.append(self._image)
        return args

    def execute(self, command: str, timeout: int = 300) -> CommandResult:
        if not self._image:
            return CommandResult(
                stdout="",
                stderr="Singularity image path not configured. "
                "Set 'image' parameter or SINGULARITY_IMAGE env var.",
                returncode=1,
            )
        with self._lock:
            try:
                result = subprocess.run(
                    [self._singularity_cmd] + self._build_args() + ["sh", "-c", command],
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
