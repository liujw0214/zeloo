"""Zeloo ``status`` subcommand — agent, gateway and system status.

Displays:
- Agent runtime state (session, model, provider, active skills)
- Gateway status (running/stopped, PID, port, version)
- System info (Python, OS, platform)
- Recent conversation summary
"""

from __future__ import annotations

import argparse
import platform
import sys
from datetime import datetime
from pathlib import Path

from zeloo_cli.subcommands import Subcommand, subcommand


@subcommand("status")
class StatusCmd(Subcommand):
    name = "status"
    help = "Show agent, gateway and system status"

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--json", action="store_true",
            help="Output status as machine-readable JSON",
        )
        parser.add_argument(
            "--agent", action="store_true",
            help="Show agent-level status only",
        )
        parser.add_argument(
            "--gateway", action="store_true",
            help="Show gateway-level status only",
        )
        parser.add_argument(
            "--system", action="store_true",
            help="Show system info only",
        )

    def run(self, args: argparse.Namespace) -> int:
        if getattr(args, "agent", False):
            return self._agent_status(args)
        if getattr(args, "gateway", False):
            return self._gateway_status(args)
        if getattr(args, "system", False):
            return self._system_status(args)
        if getattr(args, "json", False):
            return self._json_status(args)
        return self._full_status(args)

    def _format_key(self, key: str, width: int = 20) -> str:
        return f"{key:<{width}}"

    def _section(self, title: str) -> None:
        print(f"\n{'─' * 50}")
        print(f" {title}")
        print(f"{'─' * 50}")

    def _full_status(self, _args: argparse.Namespace) -> int:
        self._system_status(_args)
        self._gateway_status(_args)
        self._agent_status(_args)
        return 0

    def _system_status(self, _args: argparse.Namespace) -> int:
        self._section("System")

        py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        os_name = platform.system()
        os_release = platform.release()
        hostname = platform.node()
        cpu = platform.processor() or "unknown"

        rows = [
            ("Python", py_version),
            ("OS", f"{os_name} {os_release}"),
            ("Hostname", hostname),
            ("CPU", cpu),
            ("Architecture", platform.machine()),
            ("Zeloo", self._get_zeloo_version()),
            ("Config dir", str(self._get_zeloo_home())),
        ]
        for key, val in rows:
            print(f"  {self._format_key(key)}{val}")
        return 0

    def _gateway_status(self, _args: argparse.Namespace) -> int:
        self._section("Gateway")

        from gateway.status import (
            GatewayState,
            GatewayStatus,
            get_running_pid,
            read_gateway_state,
        )

        pid = get_running_pid()
        state = read_gateway_state()

        if pid is None or state is None:
            print("  Gateway status    stopped")
            return 0

        status = state.status if isinstance(state, GatewayState) else "unknown"
        status_color = {
            GatewayStatus.RUNNING.value: "running",
            GatewayStatus.STARTING.value: "starting",
            GatewayStatus.DRAINING.value: "draining",
            GatewayStatus.STOPPED.value: "stopped",
            GatewayStatus.FAILED.value: "FAILED",
        }.get(status, status)

        print(f"  {self._format_key('Gateway status')}{status_color}")
        print(f"  {self._format_key('PID')}{pid}")
        if state and hasattr(state, "port") and state.port:
            print(f"  {self._format_key('Port')}{state.port}")
        if state and hasattr(state, "version") and state.version:
            print(f"  {self._format_key('Version')}{state.version}")
        if state and hasattr(state, "profile") and state.profile:
            print(f"  {self._format_key('Profile')}{state.profile}")
        if state and hasattr(state, "started_at") and state.started_at:
            print(f"  {self._format_key('Started at')}{state.started_at[:19]}")
        return 0

    def _agent_status(self, _args: argparse.Namespace) -> int:
        self._section("Agent")

        from zeloo_state import SessionDB

        try:
            db = SessionDB()
            sessions = db.list_sessions(limit=5)
        except Exception as exc:
            print(f"  (session DB unavailable: {exc})")
            return 0

        if sessions:
            latest = sessions[0]
            print(f"  {self._format_key('Latest session')}{latest.get('session_id', '?')[:36]}")
            print(f"  {self._format_key('Platform')}{latest.get('platform', '?')}")
            if latest.get("created_at"):
                print(f"  {self._format_key('Created at')}{latest['created_at'][:19]}")
            print(f"  {self._format_key('Messages')}{latest.get('message_count', 0)}")
        else:
            print("  No sessions found")

        self._skills_status()
        return 0

    def _skills_status(self) -> None:
        from pathlib import Path

        skills_dirs = [
            self._get_zeloo_home() / "skills",
            Path(__file__).parent.parent.parent / "skills",
        ]
        total = 0
        for sd in skills_dirs:
            if sd.exists():
                skills = [d for d in sd.iterdir() if d.is_dir() and (d / "manifest.md").exists()]
                total += len(skills)
        print(f"  {self._format_key('Skills')}{total} loaded")

    def _json_status(self, _args: argparse.Namespace) -> int:
        import json

        from gateway.status import get_running_pid, read_gateway_state

        from zeloo_state import SessionDB

        pid = get_running_pid()
        state = read_gateway_state()
        sessions = []
        try:
            db = SessionDB()
            sessions = db.list_sessions(limit=5) or []
        except Exception:
            pass

        py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

        data = {
            "system": {
                "python": py_version,
                "os": platform.system(),
                "release": platform.release(),
                "hostname": platform.node(),
            },
            "gateway": {
                "status": "running" if pid else "stopped",
                "pid": pid,
                "port": getattr(state, "port", None) if state else None,
                "version": getattr(state, "version", None) if state else None,
                "profile": getattr(state, "profile", None) if state else None,
            },
            "agent": {
                "sessions": sessions,
            },
            "timestamp": datetime.now().isoformat(),
        }
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0

    def _get_zeloo_home(self) -> Path:
        import os

        val = os.environ.get("ZELOO_HOME", "").strip()
        if val:
            return Path(val)
        if sys.platform == "win32":
            local = os.environ.get("LOCALAPPDATA", "").strip()
            base = Path(local) if local else Path.home() / "AppData" / "Local"
            return base / "Zeloo"
        return Path.home() / ".Zeloo"

    def _get_zeloo_version(self) -> str:
        try:
            from zeloo_cli.__about__ import __version__

            return __version__
        except Exception:
            return "unknown"
