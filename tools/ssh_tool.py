"""SSH remote execution and file transfer tools.

Supports both ``paramiko`` (preferred, async-capable) and a fallback that
invokes the system ``ssh`` / ``scp`` / ``ssh-keyscan`` binaries via
``subprocess``. Connection settings can be supplied directly or loaded
from ``~/.ssh/config`` aliases.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import shlex
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from tools.base import tool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration / result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SSHConfig:
    """Connection parameters for an SSH session."""

    host: str
    port: int = 22
    user: str = "root"
    password: str | None = None
    key_path: str | None = None
    key_passphrase: str | None = None
    timeout: float = 30.0
    known_hosts_path: str | None = None
    strict_host_key_checking: bool = True

    def to_dict(self) -> dict:
        """Return a dict representation safe for logging (no secrets)."""
        d = asdict(self)
        if d.get("password"):
            d["password"] = "***"
        if d.get("key_passphrase"):
            d["key_passphrase"] = "***"
        return d


@dataclass
class SSHResult:
    """Result of a remote command execution."""

    success: bool
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: float = 0.0
    host: str = ""

    def to_dict(self) -> dict:
        """Return a dict representation."""
        return asdict(self)


# ---------------------------------------------------------------------------
# SSH client capability detection
# ---------------------------------------------------------------------------


def _paramiko_available() -> bool:
    """Return True if the optional ``paramiko`` package can be imported."""
    return importlib.util.find_spec("paramiko") is not None


# ---------------------------------------------------------------------------
# ssh/scp config-file parser
# ---------------------------------------------------------------------------


class SSHConfigParser:
    """Parse OpenSSH ``~/.ssh/config`` files into :class:`SSHConfig` objects.

    Only the subset of fields that map to :class:`SSHConfig` is honoured:
    ``Host``, ``HostName``, ``User``, ``Port``, ``IdentityFile``,
    ``IdentityAgent`` (ignored), ``StrictHostKeyChecking``, ``UserKnownHostsFile``.
    ``Match`` blocks and ``Host *`` wildcards are skipped.
    """

    _SUPPORTED_KEYS = {
        "hostname": "host",
        "user": "user",
        "port": "port",
        "identityfile": "key_path",
        "userknownhostsfile": "known_hosts_path",
        "stricthostkeychecking": "strict_host_key_checking",
    }

    def __init__(self, ssh_config_path: str | None = None) -> None:
        self._path = Path(
            ssh_config_path or os.environ.get("ZELOO_SSH_CONFIG")
            or (Path.home() / ".ssh" / "config")
        )

    @property
    def path(self) -> Path:
        """Return the resolved config-file path."""
        return self._path

    def _parse_file(self) -> list[dict]:
        """Parse the SSH config file into a list of host-block dicts.

        Returns:
            List of dicts with ``host`` (alias) and configuration overrides.
        """
        if not self._path.exists():
            return []

        blocks: list[dict] = []
        current: dict | None = None
        try:
            text = self._path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("Failed to read SSH config %s: %s", self._path, exc)
            return blocks

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.lower().startswith("match"):
                # ``Match`` blocks aren't supported by this minimal parser.
                current = None
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip().lower()
            value = value.strip()
            if key == "host":
                if value.startswith("*"):
                    current = None
                    continue
                current = {"host": value, "options": {}}
                blocks.append(current)
                continue
            if current is None or key not in self._SUPPORTED_KEYS:
                continue
            field_name = self._SUPPORTED_KEYS[key]
            if field_name == "port":
                try:
                    value = int(value)
                except ValueError:
                    continue
            elif field_name == "strict_host_key_checking":
                value = value.lower() in {"yes", "true", "1"}
            current["options"][field_name] = value
        return blocks

    def parse(self, host_alias: str) -> SSHConfig | None:
        """Resolve ``host_alias`` to an :class:`SSHConfig`.

        The first matching ``Host`` block wins. If no alias matches,
        ``None`` is returned so the caller can fall back to defaults.
        """
        for block in self._parse_file():
            if block["host"] != host_alias:
                continue
            opts = dict(block["options"])
            opts.setdefault("host", host_alias)
            # Normalise key path: expand ~ and environment variables.
            if "key_path" in opts:
                opts["key_path"] = str(Path(opts["key_path"]).expanduser())
            if "known_hosts_path" in opts:
                opts["known_hosts_path"] = str(Path(opts["known_hosts_path"]).expanduser())
            try:
                return SSHConfig(**opts)
            except TypeError:
                logger.exception("Invalid SSH config block for %s", host_alias)
                return None
        return None

    def list_hosts(self) -> list[str]:
        """Return the list of host aliases declared in the config file."""
        return [b["host"] for b in self._parse_file()]


# ---------------------------------------------------------------------------
# Main SSH tool
# ---------------------------------------------------------------------------


class SSHTool:
    """SSH client supporting execute, upload, download, and script running.

    Backend priority:

    1. ``paramiko`` (when installed) for fully async I/O and richer error
       reporting.
    2. ``subprocess`` invoking the system ``ssh`` / ``scp`` binaries as a
       fallback so the tool remains functional without extra dependencies.
    """

    def __init__(self, default_timeout: float = 30.0) -> None:
        self._default_timeout = default_timeout
        self._paramiko = _paramiko_available()
        if self._paramiko:
            try:
                import paramiko  # type: ignore[import-not-found]

                self._paramiko_mod = paramiko
            except Exception:  # pragma: no cover - defensive
                self._paramiko = False
                self._paramiko_mod = None
        else:
            self._paramiko_mod = None

    # ------------------------------------------------------------------ utils

    @staticmethod
    def _normalize(config: SSHConfig | str, ssh_config_path: str | None = None) -> SSHConfig:
        """Resolve a string alias to an :class:`SSHConfig` instance.

        If ``config`` is already an :class:`SSHConfig`, return it unchanged.
        Otherwise treat it as a host alias and look it up in the SSH config
        file. When no alias resolves, fall back to a minimal config with
        default user/port.
        """
        if isinstance(config, SSHConfig):
            return config
        parsed = SSHConfigParser(ssh_config_path).parse(config)
        if parsed is not None:
            return parsed
        return SSHConfig(host=config)

    def _backend_label(self) -> str:
        """Return a short label describing the active backend."""
        return "paramiko" if self._paramiko else "subprocess"

    # -------------------------------------------------------- paramiko path

    async def _execute_paramiko(self, command: str, config: SSHConfig) -> SSHResult:
        """Run ``command`` on the remote host via paramiko."""
        assert self._paramiko_mod is not None
        paramiko = self._paramiko_mod
        client = paramiko.SSHClient()
        if config.known_hosts_path:
            try:
                client.load_host_keys(config.known_hosts_path)
            except OSError as exc:
                logger.warning("Failed to load known_hosts %s: %s", config.known_hosts_path, exc)
        if config.strict_host_key_checking:
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
        else:
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        pkey = None
        if config.key_path:
            try:
                pkey = paramiko.RSAKey.from_private_key_file(
                    config.key_path, password=config.key_passphrase
                )
            except Exception:
                try:
                    pkey = paramiko.Ed25519Key.from_private_key_file(
                        config.key_path, password=config.key_passphrase
                    )
                except Exception as exc:  # pragma: no cover - depends on key format
                    return SSHResult(
                        success=False, stdout="", stderr=f"Failed to load key: {exc}",
                        exit_code=-1, host=config.host,
                    )

        started = time.monotonic()
        try:
            client.connect(
                hostname=config.host,
                port=config.port,
                username=config.user,
                password=config.password,
                pkey=pkey,
                timeout=config.timeout,
                allow_agent=not config.key_path,
                look_for_keys=not config.key_path,
            )
        except Exception as exc:
            return SSHResult(
                success=False, stdout="", stderr=f"Connection failed: {exc}",
                exit_code=-1, host=config.host,
            )

        try:
            stdin, stdout, stderr = client.exec_command(command, timeout=config.timeout)
            try:
                stdin.close()
            except Exception:
                pass
            exit_code = stdout.channel.recv_exit_status()
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
        except Exception as exc:
            return SSHResult(
                success=False, stdout="", stderr=f"Execution failed: {exc}",
                exit_code=-1, host=config.host,
            )
        finally:
            client.close()
        duration = (time.monotonic() - started) * 1000.0
        return SSHResult(
            success=exit_code == 0, stdout=out, stderr=err,
            exit_code=exit_code, duration_ms=duration, host=config.host,
        )

    async def _transfer_paramiko(
        self, local: str, remote: str, config: SSHConfig, upload: bool,
    ) -> bool:
        """Copy a file via paramiko's SFTP subsystem."""
        assert self._paramiko_mod is not None
        paramiko = self._paramiko_mod
        client = paramiko.SSHClient()
        if config.strict_host_key_checking:
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
        else:
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=config.host, port=config.port, username=config.user,
                password=config.password, key_filename=config.key_path,
                timeout=config.timeout, allow_agent=not config.key_path,
                look_for_keys=not config.key_path,
            )
        except Exception as exc:
            logger.warning("SFTP connect failed: %s", exc)
            return False
        try:
            sftp = client.open_sftp()
            try:
                if upload:
                    sftp.put(local, remote)
                else:
                    Path(local).parent.mkdir(parents=True, exist_ok=True)
                    sftp.get(remote, local)
            finally:
                sftp.close()
            return True
        except Exception as exc:
            logger.warning("SFTP transfer failed: %s", exc)
            return False
        finally:
            client.close()

    # ----------------------------------------------------- subprocess path

    def _build_ssh_cmd(self, command: str, config: SSHConfig) -> list[str]:
        """Build the ``ssh`` argument list for a one-shot command."""
        cmd = [
            "ssh",
            "-p", str(config.port),
            "-o", f"ConnectTimeout={int(config.timeout)}",
            "-o", "BatchMode=yes" if not config.password else "NumberOfPasswordPrompts=1",
            "-o", f"StrictHostKeyChecking={'yes' if config.strict_host_key_checking else 'no'}",
        ]
        if config.known_hosts_path:
            cmd += ["-o", f"UserKnownHostsFile={config.known_hosts_path}"]
        if config.key_path:
            cmd += ["-i", config.key_path]
        cmd += [f"{config.user}@{config.host}", "--", command]
        return cmd

    async def _run_subprocess(self, cmd: list[str], config: SSHConfig) -> tuple[int, str, str]:
        """Run ``cmd`` asynchronously and return ``(exit, stdout, stderr)``."""
        def _runner() -> tuple[int, str, str]:
            try:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True,
                    timeout=config.timeout, check=False,
                )
                return proc.returncode, proc.stdout, proc.stderr
            except subprocess.TimeoutExpired:
                return 124, "", f"Timeout after {config.timeout}s"
            except FileNotFoundError as exc:
                return 127, "", f"Command not found: {exc}"
            except Exception as exc:  # pragma: no cover - defensive
                return 1, "", str(exc)

        return await asyncio.to_thread(_runner)

    async def _execute_subprocess(self, command: str, config: SSHConfig) -> SSHResult:
        """Run ``command`` via the system ``ssh`` binary."""
        started = time.monotonic()
        cmd = self._build_ssh_cmd(command, config)
        if not shutil.which("ssh"):
            return SSHResult(
                success=False, stdout="", stderr="ssh binary not found in PATH",
                exit_code=127, host=config.host,
            )
        exit_code, out, err = await self._run_subprocess(cmd, config)
        duration = (time.monotonic() - started) * 1000.0
        return SSHResult(
            success=exit_code == 0, stdout=out, stderr=err,
            exit_code=exit_code, duration_ms=duration, host=config.host,
        )

    async def _transfer_subprocess(
        self, local: str, remote: str, config: SSHConfig, upload: bool,
    ) -> bool:
        """Copy a file using ``scp``."""
        binary = shutil.which("scp")
        if not binary:
            logger.warning("scp binary not found in PATH")
            return False
        cmd = [
            binary, "-P", str(config.port),
            "-o", f"ConnectTimeout={int(config.timeout)}",
            "-o", f"StrictHostKeyChecking={'yes' if config.strict_host_key_checking else 'no'}",
        ]
        if config.known_hosts_path:
            cmd += ["-o", f"UserKnownHostsFile={config.known_hosts_path}"]
        if config.key_path:
            cmd += ["-i", config.key_path]
        if upload:
            cmd += [local, f"{config.user}@{config.host}:{remote}"]
        else:
            cmd += [f"{config.user}@{config.host}:{remote}", local]
        exit_code, _out, err = await self._run_subprocess(cmd, config)
        if exit_code != 0:
            logger.warning("scp failed (code=%s): %s", exit_code, err.strip())
        return exit_code == 0

    # -------------------------------------------------------- public API

    async def execute_async(self, command: str, config: SSHConfig | str) -> SSHResult:
        """Execute ``command`` on the remote host asynchronously."""
        cfg = self._normalize(config)
        logger.debug("ssh execute via %s -> %s@%s", self._backend_label(), cfg.user, cfg.host)
        if self._paramiko:
            return await self._execute_paramiko(command, cfg)
        return await self._execute_subprocess(command, cfg)

    def execute(self, command: str, config: SSHConfig | str) -> SSHResult:
        """Execute ``command`` synchronously by bridging the async method."""
        return asyncio.run(self.execute_async(command, config))

    async def upload(
        self, local_path: str, remote_path: str, config: SSHConfig | str,
    ) -> bool:
        """Copy a local file to a remote host."""
        cfg = self._normalize(config)
        if self._paramiko:
            return await self._transfer_paramiko(local_path, remote_path, cfg, upload=True)
        return await self._transfer_subprocess(local_path, remote_path, cfg, upload=True)

    async def download(
        self, remote_path: str, local_path: str, config: SSHConfig | str,
    ) -> bool:
        """Copy a remote file to the local filesystem."""
        if self._paramiko:
            cfg = self._normalize(config)
            return await self._transfer_paramiko(local_path, remote_path, cfg, upload=False)
        cfg = self._normalize(config)
        return await self._transfer_subprocess(local_path, remote_path, cfg, upload=False)

    async def run_script(
        self,
        local_script: str,
        remote_path: str,
        config: SSHConfig | str,
        interpreter: str = "bash",
    ) -> SSHResult:
        """Upload a local script and execute it on the remote host.

        Args:
            local_script: Path to a local script file.
            remote_path: Destination path on the remote host (e.g.
                ``/tmp/run.sh``).
            config: Connection configuration.
            interpreter: Interpreter used to execute the uploaded script.
        """
        script_path = Path(local_script)
        if not script_path.exists():
            return SSHResult(
                success=False, stdout="", stderr=f"Local script not found: {local_script}",
                exit_code=-1, host="",
            )
        uploaded = await self.upload(str(script_path), remote_path, config)
        if not uploaded:
            return SSHResult(
                success=False, stdout="", stderr="Failed to upload script",
                exit_code=-1, host=self._normalize(config).host,
            )
        cfg = self._normalize(config)
        chmod = f"chmod +x {shlex.quote(remote_path)} && {shlex.quote(interpreter)} {shlex.quote(remote_path)}"
        return await self.execute_async(chmod, cfg)

    async def test_connection(self, config: SSHConfig | str) -> bool:
        """Return True if a lightweight command succeeds on the remote host."""
        result = await self.execute_async("echo ok", config)
        return result.success and "ok" in result.stdout

    def parse_ssh_config(
        self, host_alias: str, ssh_config_path: str | None = None,
    ) -> SSHConfig:
        """Resolve ``host_alias`` to an :class:`SSHConfig`."""
        cfg = SSHConfigParser(ssh_config_path).parse(host_alias)
        if cfg is None:
            return SSHConfig(host=host_alias)
        return cfg


# ---------------------------------------------------------------------------
# Default singleton + tool-decorated wrappers
# ---------------------------------------------------------------------------


_default_tool = SSHTool()


def _build_config(
    host: str, user: str, port: int, key_path: str | None, password: str | None,
) -> SSHConfig:
    """Build an :class:`SSHConfig` honouring SSH config aliases."""
    parsed = SSHConfigParser().parse(host)
    if parsed is not None:
        # Allow explicit CLI-style overrides to win over the parsed config.
        if user:
            parsed.user = user
        if port and port != 22:
            parsed.port = port
        if key_path:
            parsed.key_path = key_path
        if password:
            parsed.password = password
        return parsed
    return SSHConfig(
        host=host, port=port, user=user, key_path=key_path, password=password,
    )


@tool(
    name="ssh_execute",
    description="Execute a command on a remote host over SSH",
    dangerous=True, toolset="ssh",
)
def ssh_execute(
    command: str, host: str, user: str = "root", port: int = 22,
    key_path: str | None = None, password: str | None = None,
) -> dict:
    """Execute ``command`` on ``host`` and return its output.

    Args:
        command: The shell command to run remotely.
        host: Hostname or SSH config alias.
        user: SSH user (defaults to ``root``).
        port: SSH port (defaults to 22).
        key_path: Path to a private key file (optional).
        password: Plaintext password (optional, prefer ``key_path``).
    """
    cfg = _build_config(host, user, port, key_path, password)
    result = asyncio.run(_default_tool.execute_async(command, cfg))
    return result.to_dict()


@tool(
    name="ssh_upload",
    description="Upload a local file to a remote host over SSH/SFTP",
    dangerous=True, toolset="ssh",
)
def ssh_upload(
    local_path: str, remote_path: str, host: str, user: str,
    key_path: str | None = None,
) -> dict:
    """Upload ``local_path`` to ``remote_path`` on ``host``.

    Args:
        local_path: Path to the local file.
        remote_path: Destination path on the remote host.
        host: Hostname or SSH alias.
        user: SSH user.
        key_path: Optional private key path.
    """
    cfg = _build_config(host, user, 22, key_path, None)
    ok = asyncio.run(_default_tool.upload(local_path, remote_path, cfg))
    return {
        "success": ok,
        "local_path": local_path,
        "remote_path": remote_path,
        "host": cfg.host,
    }


@tool(
    name="ssh_download",
    description="Download a remote file from a host over SSH/SFTP",
    dangerous=True, toolset="ssh",
)
def ssh_download(
    remote_path: str, local_path: str, host: str, user: str,
    key_path: str | None = None,
) -> dict:
    """Download ``remote_path`` from ``host`` to ``local_path``.

    Args:
        remote_path: Path on the remote host.
        local_path: Destination path on the local filesystem.
        host: Hostname or SSH alias.
        user: SSH user.
        key_path: Optional private key path.
    """
    cfg = _build_config(host, user, 22, key_path, None)
    ok = asyncio.run(_default_tool.download(remote_path, local_path, cfg))
    return {
        "success": ok,
        "remote_path": remote_path,
        "local_path": local_path,
        "host": cfg.host,
    }


@tool(
    name="ssh_test",
    description="Test connectivity to a remote host over SSH",
    dangerous=False, toolset="ssh",
)
def ssh_test(
    host: str, user: str = "root", key_path: str | None = None,
) -> dict:
    """Verify that ``host`` is reachable via SSH.

    Args:
        host: Hostname or SSH alias.
        user: SSH user.
        key_path: Optional private key path.
    """
    cfg = _build_config(host, user, 22, key_path, None)
    ok = asyncio.run(_default_tool.test_connection(cfg))
    return {
        "success": ok,
        "host": cfg.host,
        "user": cfg.user,
        "backend": _default_tool._backend_label(),
    }