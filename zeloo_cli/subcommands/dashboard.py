"""Zeloo ``dashboard`` subcommand — web UI dashboard management."""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Any, Optional

from zeloo_cli.subcommands import Subcommand, subcommand


@subcommand("dashboard")
class DashboardCmd(Subcommand):
    name = "dashboard"
    help = "Start the web UI dashboard"

    _dashboard_process: Optional[subprocess.Popen[bytes]] = None
    _dashboard_pid_file: Optional[Path] = None

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--port", type=int, default=8765,
            help="Port to run dashboard on (default: 8765)",
        )
        parser.add_argument(
            "--host", default="127.0.0.1",
            help="Host to bind to (default: 127.0.0.1)",
        )
        parser.add_argument(
            "--stop", action="store_true",
            help="Stop a running dashboard instance",
        )
        parser.add_argument(
            "--status", action="store_true",
            help="Show dashboard running status",
        )
        parser.add_argument(
            "--no-open", action="store_true",
            help="Don't open browser automatically",
        )

    def run(self, args: argparse.Namespace) -> int:
        if getattr(args, "status", False):
            return self._status()
        if getattr(args, "stop", False):
            return self._stop()
        return self._start(
            port=getattr(args, "port", 8765),
            host=getattr(args, "host", "127.0.0.1"),
            no_open=getattr(args, "no_open", False),
        )

    def _get_zeloo_home(self) -> Path:
        val = os.environ.get("ZELOO_HOME", "").strip()
        if val:
            return Path(val)
        if sys.platform == "win32":
            local = os.environ.get("LOCALAPPDATA", "").strip()
            base = Path(local) if local else Path.home() / "AppData" / "Local"
            return base / "Zeloo"
        return Path.home() / ".Zeloo"

    def _get_dashboard_pid_file(self) -> Path:
        if self._dashboard_pid_file is None:
            self._dashboard_pid_file = self._get_zeloo_home() / "dashboard.pid"
        return self._dashboard_pid_file

    def _get_dashboard_log_file(self) -> Path:
        return self._get_zeloo_home() / "dashboard.log"

    def _is_port_in_use(self, host: str, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
                return False
            except OSError:
                return True

    def _get_dashboard_url(self, host: str, port: int) -> str:
        return f"http://{host}:{port}"

    def _read_pid_file(self) -> tuple[int | None, str | None, int | None]:
        pid_file = self._get_dashboard_pid_file()
        if not pid_file.exists():
            return None, None, None
        try:
            content = pid_file.read_text(encoding="utf-8").strip()
            parts = content.split(",")
            pid = int(parts[0]) if parts else None
            host = parts[1] if len(parts) > 1 else None
            port = int(parts[2]) if len(parts) > 2 else None
            return pid, host, port
        except Exception:
            return None, None, None

    def _write_pid_file(self, pid: int, host: str, port: int) -> None:
        pid_file = self._get_dashboard_pid_file()
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(f"{pid},{host},{port}", encoding="utf-8")

    def _clear_pid_file(self) -> None:
        pid_file = self._get_dashboard_pid_file()
        if pid_file.exists():
            pid_file.unlink()

    def _is_process_running(self, pid: int) -> bool:
        try:
            if sys.platform == "win32":
                import ctypes
                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                kernel = ctypes.windll.kernel32
                handle = kernel.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                if handle:
                    kernel.CloseHandle(handle)
                    return True
                return False
            else:
                os.kill(pid, 0)
                return True
        except (OSError, ProcessLookupError):
            return False

    def _status(self) -> int:
        pid, host, port = self._read_pid_file()

        if pid is None:
            print("Dashboard status: not running (no PID file)")
            return 0

        if not self._is_process_running(pid):
            print("Dashboard status: not running (stale PID file)")
            self._clear_pid_file()
            return 0

        url = self._get_dashboard_url(host or "127.0.0.1", port or 8765)
        print(f"Dashboard status: running")
        print(f"  PID:  {pid}")
        print(f"  URL:  {url}")
        print(f"  Host: {host or '127.0.0.1'}")
        print(f"  Port: {port or 8765}")
        return 0

    def _stop(self) -> int:
        pid, host, port = self._read_pid_file()

        if pid is None or not self._is_process_running(pid):
            print("Dashboard is not running.")
            self._clear_pid_file()
            return 0

        print(f"Stopping dashboard (PID {pid})...")

        try:
            if sys.platform == "win32":
                import ctypes
                kernel = ctypes.windll.kernel32
                kernel.GenerateConsoleCtrlEvent(0, pid)
            else:
                os.kill(pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass

        import time
        for _ in range(10):
            if not self._is_process_running(pid):
                break
            time.sleep(0.5)

        if self._is_process_running(pid):
            print("Dashboard did not stop gracefully, forcing...")
            try:
                if sys.platform == "win32":
                    import ctypes
                    kernel = ctypes.windll.kernel32
                    kernel.TerminateProcess(
                        kernel.OpenProcess(0x0001, False, pid), 1
                    )
                else:
                    os.kill(pid, signal.SIGKILL)
            except Exception:
                pass

        self._clear_pid_file()
        print("Dashboard stopped.")
        return 0

    def _find_dashboard_module(self) -> Optional[str]:
        candidates = [
            "zeloo_cli.dashboard_app:app",
            "zeloo_cli.web_app:app",
            "dash_app:app",
            "dashboard:app",
        ]

        for candidate in candidates:
            module_path = candidate.split(":")[0]
            try:
                __import__(module_path)
                return candidate
            except ImportError:
                continue

        return None

    def _start(self, port: int, host: str, no_open: bool) -> int:
        if self._is_port_in_use(host, port):
            existing_pid, existing_host, existing_port = self._read_pid_file()
            if existing_pid and self._is_process_running(existing_pid):
                url = self._get_dashboard_url(existing_host or "127.0.0.1", existing_port or port)
                print(f"Dashboard already running at {url}")
                print(f"PID: {existing_pid}")
                return 1
            print(f"Port {port} is in use, but dashboard process is not running. Clearing stale state.")

        dash_module = self._find_dashboard_module()
        if dash_module is None:
            print("Dashboard module not found.")
            print("The web dashboard requires a web application module.")
            print("Check that zeloo_cli.dashboard_app or zeloo_cli.web_app is available.")
            return 1

        print(f"Starting dashboard on {host}:{port}...")

        log_file = self._get_dashboard_log_file()
        log_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            if sys.platform == "win32":
                creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP
                proc = subprocess.Popen(
                    [sys.executable, "-m", dash_module.replace(":", "."), "--port", str(port), "--host", host],
                    cwd=str(Path(__file__).parent.parent.parent),
                    stdout=open(log_file, "w", encoding="utf-8"),
                    stderr=subprocess.STDOUT,
                    creationflags=creation_flags,
                )
            else:
                proc = subprocess.Popen(
                    [sys.executable, "-m", dash_module.replace(":", "."), "--port", str(port), "--host", host],
                    cwd=str(Path(__file__).parent.parent.parent),
                    stdout=open(log_file, "w", encoding="utf-8"),
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )

            pid = proc.pid
            self._write_pid_file(pid, host, port)

            import time
            for i in range(30):
                time.sleep(0.5)
                if proc.poll() is not None:
                    print(f"Dashboard process exited unexpectedly (code {proc.returncode})")
                    self._clear_pid_file()
                    return 1
                if not self._is_port_in_use(host, port):
                    break

            url = self._get_dashboard_url(host, port)
            print(f"Dashboard started successfully!")
            print(f"  URL: {url}")
            print(f"  PID: {pid}")
            print(f"  Log: {log_file}")

            if not no_open:
                print("Opening browser...")
                webbrowser.open(url)

            return 0

        except Exception as exc:
            print(f"Failed to start dashboard: {exc}", file=sys.stderr)
            self._clear_pid_file()
            return 1
