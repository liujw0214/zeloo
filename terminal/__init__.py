"""Zeloo Agent terminal backends.

7 backends from local development to HPC environments:
- local:      subprocess execution (zero config)
- ssh:        paramiko-based remote execution
- docker:     Docker container isolation
- modal:      Modal cloud serverless
- daytona:    Daytona cloud sandbox
- vercel_sandbox: Vercel Functions runtime
- singularity: HPC Singularity/Apptainer containers
"""

from terminal.base import CommandResult, TerminalBackend
from terminal.daytona import DaytonaTerminalBackend
from terminal.docker import DockerTerminalBackend
from terminal.local import LocalTerminalBackend
from terminal.modal import ModalTerminalBackend
from terminal.singularity import SingularityTerminalBackend
from terminal.ssh import SSHConfig, SSHTerminalBackend
from terminal.vercel_sandbox import VercelSandboxTerminalBackend


def create_backend(name: str, **kwargs) -> TerminalBackend:
    """Factory: create a terminal backend by name."""
    backends = {
        "local": LocalTerminalBackend,
        "ssh": SSHTerminalBackend,
        "docker": DockerTerminalBackend,
        "modal": ModalTerminalBackend,
        "daytona": DaytonaTerminalBackend,
        "vercel_sandbox": VercelSandboxTerminalBackend,
        "singularity": SingularityTerminalBackend,
    }
    if name not in backends:
        raise ValueError(
            f"Unknown terminal backend '{name}'. "
            f"Available: {list(backends.keys())}"
        )
    return backends[name](**kwargs)


__all__ = [
    "CommandResult",
    "TerminalBackend",
    "LocalTerminalBackend",
    "SSHTerminalBackend",
    "SSHConfig",
    "DockerTerminalBackend",
    "ModalTerminalBackend",
    "DaytonaTerminalBackend",
    "VercelSandboxTerminalBackend",
    "SingularityTerminalBackend",
    "create_backend",
]
