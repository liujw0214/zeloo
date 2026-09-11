"""Gateway process management — Zeloo's equivalent of Hermes hermes_cli/gateway.py.

Handles:
- start/stop/restart/status/install/uninstall of the gateway process
- Foreground run and supervised mode
- Windows Service, systemd, launchd, s6 integration
- Health check (heartbeat file + loop tick)
- Respawn storm detection
- Orphan process reaping
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from gateway.status import (
    GatewayState,
    GatewayStatus,
    _get_zeloo_home,
    clear_planned_stop_marker,
    get_running_pid,
    is_gateway_running,
    kill_gateway_processes,
    reap_unsupervised_gateway_orphans,
    read_gateway_state,
    record_start_and_check_storm,
    remove_pid_file,
    write_gateway_state,
    write_planned_stop_marker,
    write_pid_file,
)
from hermes_startup_watchdog import (
    arm_startup_watchdog,
    disarm_startup_watchdog,
    kick_startup_watchdog,
    report_startup_progress,
)

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")
IS_MACOS = sys.platform == "darwin"

GATEWAY_KIND = "zeloo-gateway"
DRAIN_TIMEOUT_S = 180.0
DEFAULT_HEALTH_CHECK_TIMEOUT_S = 5.0
_GATEWAY_LOOP_ALIVE = "alive"
_GATEWAY_LOOP_WEDGED = "wedged"
_GATEWAY_LOOP_UNKNOWN = "unknown"
DEFAULT_LOOP_LIVENESS_STALE_AFTER_S = 60.0
_LOOP_TICK_ABSENT = "absent"


@dataclass(frozen=True)
class GatewayRuntimeSnapshot:
    manager: str
    service_installed: bool = False
    service_running: bool = False
    gateway_pids: tuple[int, ...] = ()
    service_scope: Optional[str] = None

    @property
    def running(self) -> bool:
        return self.service_running or bool(self.gateway_pids)


def _is_wsl() -> bool:
    try:
        return ".wsl." in subprocess.check_output(
            ["uname", "-r"], text=True, timeout=3
        ).lower()
    except Exception:
        return False


def _wsl_systemd_operational() -> bool:
    if not (_is_wsl() and IS_LINUX):
        return False
    try:
        result = subprocess.run(
            ["systemctl", "show", "--property=ActiveState", "basic.target"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return "ActiveState=active" in result.stdout
    except Exception:
        return False


def _supports_systemd_services() -> bool:
    if not IS_LINUX:
        return False
    if _is_wsl() and not _wsl_systemd_operational():
        return False
    try:
        subprocess.run(
            ["systemctl", "--user", "show", "--property=ControlGroup", "slice"],
            capture_output=True,
            timeout=5,
        )
        return True
    except Exception:
        return False


def _supports_launchd() -> bool:
    return IS_MACOS


def _supports_windows_service() -> bool:
    return IS_WINDOWS


def _install_windows_service() -> int:
    """Install Zeloo as a Windows Service by invoking the bundled PowerShell script.

    The PowerShell script (packaging/windows/install-service.ps1) requires
    administrator elevation, so we re-launch it via Start-Process -Verb RunAs.
    A UAC prompt will appear; if the user cancels, the call times out.
    """
    repo_root = Path(__file__).resolve().parent.parent
    ps_script = repo_root / "packaging" / "windows" / "install-service.ps1"

    if not ps_script.exists():
        print(f"PowerShell script not found: {ps_script}")
        return 1

    print("Installing Windows Service (requires admin)...")
    ps_cmd = (
        f"Start-Process powershell -ArgumentList "
        f"'\"-NoProfile -ExecutionPolicy Bypass -File \\\"{ps_script}\\\"\"' "
        f"-Verb RunAs -Wait"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        print("Install timed out (user cancelled UAC?).")
        return 1
    except FileNotFoundError:
        print("PowerShell not found on PATH.")
        return 1

    if result.returncode == 0:
        print("Windows Service installed.")
        print("  Start: Start-Service Zeloo")
        print("  Stop:  Stop-Service  Zeloo")
        return 0

    print(f"Install failed: {result.stderr}")
    return 1


def _pid_file_path(home: Optional[Path] = None) -> Path:
    base = home or _get_zeloo_home()
    return base / "state" / "gateway.pid"


def _heartbeat_path(home: Optional[Path] = None) -> Path:
    base = home or _get_zeloo_home()
    return base / "state" / "gateway.heartbeat"


def _tick_socket_path(home: Optional[Path] = None) -> Path:
    base = home or _get_zeloo_home()
    return base / "state" / f"gateway.loop-tick.{os.getpid()}.sock"


def _find_free_port(start: int = 9113, end: int = 9200) -> int:
    for port in range(start, end):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    return start


def _probe_loop_tick_tcp(port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as sock:
            sock.sendall(b"ping")
            data = sock.recv(16)
            return bool(data)
    except Exception:
        return False


def _probe_loop_tick_socket(pid: int, home: Optional[Path] = None) -> bool:
    sock_path = home / "state" / f"gateway.loop-tick.{pid}.sock" if home else None
    if sock_path is None:
        return False
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.settimeout(1.0)
        sock.sendto(b"ping", str(sock_path))
        sock.recv(16)
        return True
    except Exception:
        return False
    except (AttributeError, TypeError):
        return False


def classify_gateway_loop_state(
    pid: int,
    home: Optional[Path] = None,
    stale_after: float = DEFAULT_LOOP_LIVENESS_STALE_AFTER_S,
    tick_timeout: float = 1.0,
) -> str:
    hb_path = _heartbeat_path(home)
    try:
        mtime = hb_path.stat().st_mtime
        payload = json.loads(hb_path.read_text(encoding="utf-8"))
        heartbeat_pid = int(payload.get("pid", 0))
    except Exception:
        return _GATEWAY_LOOP_UNKNOWN

    if heartbeat_pid <= 0 or heartbeat_pid != pid:
        return _GATEWAY_LOOP_UNKNOWN

    tcp_port = payload.get("loop_tick_tcp_port")
    try:
        tcp_port_int = int(tcp_port) if tcp_port is not None else None
    except (TypeError, ValueError):
        tcp_port_int = None

    if tcp_port_int is not None and tcp_port_int > 0:
        witness = _probe_loop_tick_tcp(tcp_port_int, timeout=tick_timeout)
    else:
        witness = _probe_loop_tick_socket(pid, home, timeout=tick_timeout)

    if witness is True:
        return _GATEWAY_LOOP_ALIVE

    age = time.time() - mtime
    if age <= stale_after:
        if witness is False:
            return _GATEWAY_LOOP_UNKNOWN
        return _GATEWAY_LOOP_ALIVE

    tick_armed = payload.get("loop_tick_socket", _LOOP_TICK_ABSENT)
    if tick_armed == _LOOP_TICK_ABSENT:
        return _GATEWAY_LOOP_WEDGED
    if witness is False:
        return _GATEWAY_LOOP_WEDGED
    return _GATEWAY_LOOP_UNKNOWN


def _gateway_argv(home: Optional[Path] = None, port: Optional[int] = None) -> list[str]:
    python = sys.executable
    base = home or _get_zeloo_home()
    if port is None:
        port = 9113
    return [
        python, "-m", "gateway.run",
        "--port", str(port),
        "--home", str(base),
    ]


def _kill_pid(pid: int, grace_s: float = 10.0) -> bool:
    try:
        write_planned_stop_marker(pid)
    except Exception:
        pass
    try:
        os.kill(pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        return True
    except PermissionError:
        print(f"⚠ Permission denied to kill PID {pid}")
        return False

    deadline = time.time() + grace_s
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return True
        time.sleep(0.25)
    try:
        os.kill(pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        return True
    return True


def _wait_for_stop(pid: int, timeout_s: float = 30.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return True
        time.sleep(0.5)
    return False


def _write_heartbeat(
    pid: int,
    port: int,
    home: Optional[Path] = None,
    tick_socket: bool = False,
) -> None:
    hb_path = _heartbeat_path(home)
    hb_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pid": pid,
        "port": port,
        "timestamp": time.time(),
        "loop_tick_socket": tick_socket,
    }
    try:
        from gateway.status import atomic_json_write

        atomic_json_write(hb_path, payload)
    except Exception:
        hb_path.write_text(json.dumps(payload), encoding="utf-8")


def start_gateway(
    home: Optional[Path] = None,
    port: Optional[int] = None,
    supervised: bool = False,
    force: bool = False,
) -> int:
    base = home or _get_zeloo_home()

    existing = get_running_pid(base)
    if existing:
        if not force:
            print(f"Gateway already running (PID {existing}).")
            print(f"  Use --force to replace.")
            return 1
        print(f"Stopping existing gateway (PID {existing}) first...")
        stop_gateway(home=base)

    storm = record_start_and_check_storm()
    if storm:
        backoff_s = storm["backoff_s"]
        print(
            f"⚠ Respawn storm detected: {storm['count']} starts in {storm['window_s']:.0f}s.\n"
            f"  Sleeping {backoff_s:.0f}s before starting. Ctrl-C to abort."
        )
        time.sleep(backoff_s)

    if port is None:
        try:
            cfg = base / "config.yaml"
            if cfg.exists():
                import yaml

                data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
                port = int(
                    data.get("gateway", {}).get("api", {}).get("port", 9113)
                )
        except Exception:
            port = 9113

    argv = _gateway_argv(base, port)
    env = dict(os.environ)
    env["ZELOO_HOME"] = str(base)

    if supervised:
        print(f"[supervised] Starting gateway: {' '.join(argv)}")
        proc = subprocess.Popen(
            argv,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        pid = proc.pid
    else:
        if IS_WINDOWS:
            DETACHED_PROCESS = 0x00000008
            CREATE_NO_WINDOW = 0x08000000
            proc = subprocess.Popen(
                argv,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
            )
        else:
            start_new_session = hasattr(os, "setsid") and not IS_WINDOWS
            kwargs = {"start_new_session": start_new_session}
            proc = subprocess.Popen(
                argv,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                **kwargs,
            )
        pid = proc.pid

    write_pid_file(pid, base)

    print(f"Gateway started (PID {pid}, port {port}).")

    for i in range(20):
        time.sleep(0.5)
        if is_gateway_running(base):
            state = GatewayState(
                kind=GATEWAY_KIND,
                status=GatewayStatus.RUNNING.value,
                pid=pid,
                port=port,
                started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                profile="default",
                version="0.16.0",
            )
            write_gateway_state(state, base)
            print(f"Gateway is healthy.")
            return 0

    print(f"⚠ Gateway may have failed to start. Check logs.")
    return 1


def stop_gateway(home: Optional[Path] = None, drain: bool = True) -> bool:
    base = home or _get_zeloo_home()
    pid = get_running_pid(base)

    if pid is None:
        return _reap_and_stop_orphans(base)

    print(f"Stopping gateway (PID {pid})...")

    if drain:
        write_planned_stop_marker(pid, base)
        state = read_gateway_state(base)
        if state:
            state.status = GatewayStatus.DRAINING.value
            write_gateway_state(state, base)
        print(f"Gateway entering drain mode ({DRAIN_TIMEOUT_S}s)...")
        _kill_pid(pid)
        stopped = _wait_for_stop(pid, DRAIN_TIMEOUT_S)
        if not stopped:
            print(f"⚠ Gateway did not stop gracefully; sending SIGKILL.")
            _kill_pid(pid, grace_s=2.0)
    else:
        _kill_pid(pid, grace_s=0.0)

    remove_pid_file(base)
    clear_planned_stop_marker(base)

    _reap_and_stop_orphans(base)
    return True


def _reap_and_stop_orphans(home: Optional[Path] = None) -> bool:
    try:
        killed = reap_unsupervised_gateway_orphans(home)
        if killed:
            print(f"Reaped orphan gateway processes: {killed}")
    except Exception:
        pass
    return True


def restart_gateway(
    home: Optional[Path] = None,
    port: Optional[int] = None,
    drain: bool = True,
) -> int:
    print("Restarting gateway...")
    stop_gateway(home=home, drain=drain)
    return start_gateway(home=home, port=port)


def get_gateway_runtime_snapshot(home: Optional[Path] = None) -> GatewayRuntimeSnapshot:
    base = home or _get_zeloo_home()
    pids: list[int] = []

    pid = get_running_pid(base)
    if pid and is_gateway_running(base):
        pids = [pid]

    manager = "none"
    service_installed = False
    service_running = False

    if _supports_systemd_services():
        manager = "systemd"
        try:
            result = subprocess.run(
                ["systemctl", "--user", "is-active", "zeloo-gateway.service"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            service_running = result.stdout.strip() == "active"
            service_installed = service_running
        except Exception:
            pass

    elif _supports_launchd():
        manager = "launchd"
        try:
            label = "ai.zeloo.gateway"
            result = subprocess.run(
                ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            service_running = "pid" in result.stdout.lower()
            service_installed = service_running
        except Exception:
            pass

    elif _supports_windows_service():
        manager = "windows-service"

    return GatewayRuntimeSnapshot(
        manager=manager,
        service_installed=service_installed,
        service_running=service_running,
        gateway_pids=tuple(pids),
        service_scope="default" if service_installed else None,
    )


def run_gateway_foreground(
    home: Optional[Path] = None,
    port: Optional[int] = None,
) -> int:
    base = home or _get_zeloo_home()
    if port is None:
        port = 9113

    print(f"Starting gateway in foreground (port {port}, home {base})...")

    watchdog = arm_startup_watchdog()
    report_startup_progress("gateway_bootstrap", 30.0)

    try:
        from gateway.run import main as gateway_main

        disarm_startup_watchdog()
        return gateway_main(port=port, home=base)
    except KeyboardInterrupt:
        print("\nGateway stopped by user.")
        return 0
    except Exception as exc:
        logger.exception("Gateway failed to start")
        print(f"⚠ Gateway error: {exc}")
        return 1


def cmd_gateway_run(args: Any) -> int:
    home = Path(args.home) if getattr(args, "home", None) else None
    port = getattr(args, "port", None)
    supervised = getattr(args, "supervised", False)
    return start_gateway(home=home, port=port, supervised=supervised)


def cmd_gateway_start(args: Any) -> int:
    home = Path(args.home) if getattr(args, "home", None) else None
    port = getattr(args, "port", None)
    return start_gateway(home=home, port=port)


def cmd_gateway_stop(args: Any) -> int:
    home = Path(args.home) if getattr(args, "home", None) else None
    drain = not getattr(args, "no_drain", False)
    stop_gateway(home=home, drain=drain)
    return 0


def cmd_gateway_restart(args: Any) -> int:
    home = Path(args.home) if getattr(args, "home", None) else None
    port = getattr(args, "port", None)
    drain = not getattr(args, "no_drain", False)
    return restart_gateway(home=home, port=port, drain=drain)


def cmd_gateway_status(args: Any) -> int:
    home = Path(args.home) if getattr(args, "home", None) else None
    base = home or _get_zeloo_home()

    snapshot = get_gateway_runtime_snapshot(base)
    pid = get_running_pid(base)
    state = read_gateway_state(base)

    print(f"Gateway Runtime Status")
    print(f"  Manager:    {snapshot.manager}")
    print(f"  Installed: {snapshot.service_installed}")
    print(f"  Running:    {snapshot.running}")

    if pid:
        print(f"  PID file:  {pid}")
        loop_state = classify_gateway_loop_state(pid, base)
        print(f"  Loop:      {loop_state}")
    else:
        print(f"  PID file:  (none)")

    if state:
        print(f"  State:     {state.status}")
        print(f"  Port:      {state.port}")
        print(f"  Agents:    {state.agent_count}")
        print(f"  In-flight: {state.in_flight_count}")
        print(f"  Started:   {state.started_at}")

    return 0


def cmd_gateway_install_service(args: Any) -> int:
    """Install Zeloo gateway as a system service.

    On Linux: writes systemd user-level service.
    On macOS: writes user-level LaunchAgent.
    On Windows: invokes packaging/windows/install-service.ps1 via PowerShell.
    """
    if _supports_systemd_services():
        return _install_systemd_service()
    elif _supports_launchd():
        return _install_launchd_service()
    elif _supports_windows_service():
        return _install_windows_service()
    else:
        print("No supported service manager found.")
        return 1


def cmd_gateway_uninstall_service(args: Any) -> int:
    if _supports_systemd_services():
        return _uninstall_systemd_service()
    elif _supports_launchd():
        return _uninstall_launchd_service()
    else:
        print("No supported service manager found.")
        return 1


def _install_systemd_service() -> int:
    base = _get_zeloo_home()
    unit = f"""[Unit]
Description=Zeloo Gateway
After=network.target

[Service]
Type=simple
WorkingDirectory={base}
ExecStart={sys.executable} -m gateway.run --port 9113 --home {base}
Restart=on-failure
RestartSec=5
Environment=ZELOO_HOME={base}
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
"""
    unit_path = Path.home() / ".config" / "systemd" / "user" / "zeloo-gateway.service"
    unit_path.parent.mkdir(parents=True, exist_ok=True)
    unit_path.write_text(unit, encoding="utf-8")
    try:
        subprocess.run(["systemctl", "--user", "daemon-reload"], timeout=10)
        subprocess.run(["systemctl", "--user", "enable", "zeloo-gateway.service"], timeout=10)
        subprocess.run(["systemctl", "--user", "start", "zeloo-gateway.service"], timeout=10)
        print("systemd service installed and started.")
        return 0
    except Exception as exc:
        print(f"Failed to install systemd service: {exc}")
        return 1


def _uninstall_systemd_service() -> int:
    try:
        subprocess.run(["systemctl", "--user", "stop", "zeloo-gateway.service"], timeout=10)
        subprocess.run(["systemctl", "--user", "disable", "zeloo-gateway.service"], timeout=10)
        unit_path = Path.home() / ".config" / "systemd" / "user" / "zeloo-gateway.service"
        unit_path.unlink(missing_ok=True)
        subprocess.run(["systemctl", "--user", "daemon-reload"], timeout=10)
        print("systemd service uninstalled.")
        return 0
    except Exception as exc:
        print(f"Failed to uninstall systemd service: {exc}")
        return 1


def _install_launchd_service() -> int:
    base = _get_zeloo_home()
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>ai.zeloo.gateway</string>
    <key>ProgramArguments</key>
    <array>
        <string>{sys.executable}</string>
        <string>-m</string>
        <string>gateway.run</string>
        <string>--port</string>
        <string>9113</string>
        <string>--home</string>
        <string>{base}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>EnvironmentVariables</key>
    <dict>
        <key>ZELOO_HOME</key>
        <string>{base}</string>
    </dict>
</dict>
</plist>
"""
    plist_path = Path.home() / "Library" / "LaunchAgents" / "ai.zeloo.gateway.plist"
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_text(plist, encoding="utf-8")
    try:
        subprocess.run(["launchctl", "load", str(plist_path)], timeout=10)
        print("launchd service installed.")
        return 0
    except Exception as exc:
        print(f"Failed to install launchd service: {exc}")
        return 1


def _uninstall_launchd_service() -> int:
    plist_path = Path.home() / "Library" / "LaunchAgents" / "ai.zeloo.gateway.plist"
    try:
        subprocess.run(["launchctl", "unload", str(plist_path)], timeout=10)
        plist_path.unlink(missing_ok=True)
        print("launchd service uninstalled.")
        return 0
    except Exception as exc:
        print(f"Failed to uninstall launchd service: {exc}")
        return 1
