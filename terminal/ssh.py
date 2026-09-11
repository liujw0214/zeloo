"""SSH terminal backend — executes commands on a remote server via SSH."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .base import CommandResult, TerminalBackend


@dataclass
class SSHConfig:
    host: str
    port: int = 22
    user: str = ""
    password: str = ""
    key_path: Path | None = None


class SSHTerminalBackend(TerminalBackend):
    """Execute commands on a remote server via SSH.

    Requires: paramiko (pip install paramiko)
    Supports both password and private-key authentication.
    """

    name = "ssh"

    @property
    def host(self) -> str:
        return self._config.host

    def __init__(
        self,
        config: SSHConfig | dict[str, Any] | None = None,
        *,
        host: str = "",
        port: int = 22,
        username: str = "",
        password: str = "",
        key_path: Path | None = None,
    ) -> None:
        if config is not None:
            if isinstance(config, dict):
                cfg = SSHConfig(**config)
            else:
                cfg = config
        else:
            cfg = SSHConfig(host=host, port=port, user=username, password=password, key_path=key_path)
        self._config = cfg
        self._client: Any = None

    def _get_client(self) -> Any:
        import paramiko

        if self._client is None:
            self._client = paramiko.SSHClient()
            self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            connect_kwargs: dict[str, Any] = {
                "hostname": self._config.host,
                "port": self._config.port,
            }
            if self._config.key_path:
                connect_kwargs["key_filename"] = str(self._config.key_path)
            elif self._config.password:
                connect_kwargs["password"] = self._config.password
            if self._config.user:
                connect_kwargs["username"] = self._config.user
            self._client.connect(**connect_kwargs)
        return self._client

    def execute(self, command: str, timeout: int = 30) -> CommandResult:
        client = self._get_client()
        _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        return CommandResult(
            stdout=stdout.read().decode("utf-8", errors="replace"),
            stderr=stderr.read().decode("utf-8", errors="replace"),
            returncode=exit_code,
            timed_out=False,
        )

    def close(self) -> None:
        if self._client:
            self._client.close()
            self._client = None


SSHTerminalAdapter = SSHTerminalBackend
