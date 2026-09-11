"""Gateway process status — PID file, runtime state, and lifecycle tracking.

Minimal reimplementation of Hermes gateway/status.py for Zeloo.
Handles:
- PID file management (get_running_pid, write_pid_file, remove_pid_file)
- Runtime state JSON (GatewayState: running/draining/stopped)
- Planned-stop marker for graceful shutdown
- Orphan process reaping
- Respawn storm detection
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_RUNTIME_STATUS_FILE = "gateway_state.json"
_STATE_DIR = "state"
_PID_FILE = "gateway.pid"
_GATEWAY_KIND = "zeloo-gateway"
_PLANNED_STOP_FILE = "planned_stop.marker"

_IS_WINDOWS = sys.platform == "win32"


def _get_zeloo_home() -> Path:
    val = os.environ.get("ZELOO_HOME", "").strip()
    if val:
        return Path(val)
    if _IS_WINDOWS:
        local = os.environ.get("LOCALAPPDATA", "").strip()
        base = Path(local) if local else Path.home() / "AppData" / "Local"
        return base / "Zeloo"
    return Path.home() / ".Zeloo"


def _pid_file_path(home: Optional[Path] = None) -> Path:
    base = home or _get_zeloo_home()
    return base / _STATE_DIR / _PID_FILE


def _state_file_path(home: Optional[Path] = None) -> Path:
    base = home or _get_zeloo_home()
    return base / _STATE_DIR / _RUNTIME_STATUS_FILE


def _planned_stop_path(home: Optional[Path] = None) -> Path:
    base = home or _get_zeloo_home()
    return base / _STATE_DIR / _PLANNED_STOP_FILE


class GatewayStatus(str, Enum):
    STARTING = "starting"
    RUNNING = "running"
    DRAINING = "draining"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass
class GatewayState:
    kind: str = _GATEWAY_KIND
    status: str = GatewayStatus.STARTING.value
    pid: int = 0
    port: int = 0
    started_at: str = ""
    profile: str = "default"
    version: str = ""
    agent_count: int = 0
    in_flight_count: int = 0
    error: Optional[str] = None
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_pid_file(pid: int, home: Optional[Path] = None) -> None:
    path = _pid_file_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(pid), encoding="utf-8")


def get_running_pid(home: Optional[Path] = None) -> Optional[int]:
    path = _pid_file_path(home)
    if not path.exists():
        return None
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
        if _pid_exists(pid):
            return pid
    except (ValueError, OSError):
        pass
    return None


def remove_pid_file(home: Optional[Path] = None) -> None:
    try:
        _pid_file_path(home).unlink(missing_ok=True)
    except OSError:
        pass


def write_planned_stop_marker(pid: int, home: Optional[Path] = None) -> None:
    path = _planned_stop_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pid": pid, "timestamp": _utc_now_iso()}), encoding="utf-8")


def clear_planned_stop_marker(home: Optional[Path] = None) -> None:
    try:
        _planned_stop_path(home).unlink(missing_ok=True)
    except OSError:
        pass


def _pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        if _IS_WINDOWS:
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            GENERIC_RIGHT_NONE = 0
            handle = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, GENERIC_RIGHT_NONE, pid
            )
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        else:
            os.kill(pid, 0)
            return True
    except (OSError, ProcessLookupError, PermissionError):
        return False


def write_gateway_state(state: GatewayState, home: Optional[Path] = None) -> None:
    path = _state_file_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    state.updated_at = _utc_now_iso()
    atomic_json_write(path, state.to_dict())


def read_gateway_state(home: Optional[Path] = None) -> Optional[GatewayState]:
    path = _state_file_path(home)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return GatewayState(**data)
    except (json.JSONDecodeError, TypeError, OSError):
        return None


def write_gateway_state_if_clean(state: GatewayState, home: Optional[Path] = None) -> None:
    path = _state_file_path(home)
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing.get("status") == GatewayStatus.DRAINING.value:
                return
        except Exception:
            pass
    write_gateway_state(state, home)


def kill_gateway_processes(
    pids: list[int],
    grace_s: float = 5.0,
    force: bool = False,
) -> list[int]:
    killed = []
    for pid in pids:
        if not _pid_exists(pid):
            continue
        try:
            sig = signal.SIGKILL if force else signal.SIGTERM
            os.kill(pid, sig)
            killed.append(pid)
        except (OSError, ProcessLookupError, PermissionError):
            pass

    if not force:
        deadline = time.time() + grace_s
        for pid in killed:
            while time.time() < deadline:
                if not _pid_exists(pid):
                    break
                time.sleep(0.1)
        for pid in killed:
            if _pid_exists(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    pass
    return killed


def _get_gateway_webhook_port(home: Optional[Path] = None) -> int:
    try:
        cfg_path = home or _get_zeloo_home()
        config_file = cfg_path / "config.yaml"
        if config_file.exists():
            import yaml

            data = yaml.safe_load(config_file.read_text(encoding="utf-8"))
            return int(data.get("gateway", {}).get("api", {}).get("port", 9113))
    except Exception:
        pass
    return 9113


def _find_orphans_by_port(port: int) -> list[int]:
    orphans = []
    if not _IS_WINDOWS:
        try:
            import subprocess

            result = subprocess.run(
                ["ss", "-tlnp", f"sport = :{port}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in result.stdout.splitlines():
                if f":{port}" in line:
                    parts = line.split()
                    for p in parts:
                        if "pid=" in p:
                            pid_str = p.split("=")[1].split(",")[0]
                            try:
                                orphans.append(int(pid_str))
                            except ValueError:
                                pass
        except Exception:
            pass
    return orphans


def reap_unsupervised_gateway_orphans(
    home: Optional[Path] = None,
    extra_exclude: Optional[set[int]] = None,
) -> list[int]:
    own_pid = get_running_pid(home)
    exclude = (extra_exclude or set()) | {os.getpid(), own_pid} - {None}
    port = _get_gateway_webhook_port(home)
    candidates = _find_orphans_by_port(port)
    to_kill = [p for p in candidates if p not in exclude]
    return kill_gateway_processes(to_kill)


def _get_starts_log_path() -> Path:
    return _get_zeloo_home() / "logs" / "gateway-starts.log"


def record_start_and_check_storm(
    max_starts: int = 5,
    window_s: float = 120.0,
    backoff_cap_s: float = 300.0,
) -> Optional[dict[str, Any]]:
    try:
        path = _get_starts_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()

        existing: list[float] = []
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    existing.append(float(line.strip()))
                except ValueError:
                    continue

        existing.append(now)
        recent = [ts for ts in existing if now - ts <= window_s]

        path.write_text(
            "\n".join(str(ts) for ts in recent[-max_starts * 2:]),
            encoding="utf-8",
        )

        if len(recent) > max_starts:
            backoff_s = min(backoff_cap_s, 2.0 ** (len(recent) - max_starts) * 10.0)
            return {
                "count": len(recent),
                "window_s": window_s,
                "backoff_s": backoff_s,
            }
    except Exception:
        pass
    return None


def atomic_json_write(path: Path, data: dict[str, Any]) -> None:
    path_tmp = path.with_suffix(".tmp")
    try:
        path_tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        path_tmp.replace(path)
    except OSError:
        if path_tmp.exists():
            try:
                path_tmp.unlink()
            except OSError:
                pass
        raise


def is_gateway_running(home: Optional[Path] = None) -> bool:
    return get_running_pid(home) is not None
