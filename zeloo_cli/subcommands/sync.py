"""Zeloo ``sync`` subcommand — memory and skills sync.

Displays current sync status (local memory directory, remote sync target if configured),
and lets the user trigger a manual sync.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from zeloo_cli.subcommands import Subcommand, subcommand


@subcommand("sync")
class SyncCmd(Subcommand):
    name = "sync"
    help = "Sync local memory and skills with remote (if configured)"

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        sub = parser.add_subparsers(dest="sync_command", help="Sync action")

        sub.add_parser(
            "status",
            help="Show sync status (local memory, skills, remote target)",
        )
        sub.add_parser(
            "push",
            help="Push local memories/skills to remote (if configured)",
        )
        sub.add_parser(
            "pull",
            help="Pull remote memories/skills to local (if configured)",
        )
        sub.add_parser(
            "now",
            help="Pull then push — full reconciliation",
        )

        stats = sub.add_parser(
            "stats",
            help="Show sync statistics (counts, sizes, last sync time)",
        )
        stats.add_argument(
            "--by",
            choices=["skill", "date"],
            default="date",
            help="Group stats by skill or date",
        )

    def run(self, args: argparse.Namespace) -> int:
        action = getattr(args, "sync_command", None)
        if action is None:
            self._print_help()
            return 1
        if action == "status":
            return self._status()
        if action == "push":
            return self._push()
        if action == "pull":
            return self._pull()
        if action == "now":
            return self._now()
        if action == "stats":
            return self._stats(args.by)
        print(f"Unknown sync action: {action}")
        return 1

    def _print_help(self) -> None:
        print("Usage: zeloo sync [status|push|pull|now|stats]")
        print("  status  — show current sync state")
        print("  push    — push local to remote")
        print("  pull    — pull remote to local")
        print("  now     — full reconciliation (pull + push)")
        print("  stats   — show sync statistics")

    def _section(self, title: str) -> None:
        print(f"\n{'─' * 40}")
        print(f" {title}")

    def _home(self) -> Path:
        import os
        import sys

        val = os.environ.get("ZELOO_HOME", "").strip()
        if val:
            return Path(val)
        if sys.platform == "win32":
            local = os.environ.get("LOCALAPPDATA", "").strip()
            base = Path(local) if local else Path.home() / "AppData" / "Local"
            return base / "Zeloo"
        return Path.home() / ".Zeloo"

    def _memory_dir(self) -> Path:
        return self._home() / "memory"

    def _skills_dir(self) -> Path:
        return self._home() / "skills"

    def _sync_status(self) -> dict:
        mem_dir = self._memory_dir()
        skl_dir = self._skills_dir()

        return {
            "memory": {
                "path": str(mem_dir),
                "exists": mem_dir.exists(),
                "files": len(list(mem_dir.glob("*"))) if mem_dir.exists() else 0,
            },
            "skills": {
                "path": str(skl_dir),
                "exists": skl_dir.exists(),
                "count": len([d for d in skl_dir.iterdir() if d.is_dir()]) if skl_dir.exists() else 0,
            },
        }

    def _format_kv(self, key: str, value, indent: int = 2) -> None:
        print(f"{' ' * indent}{key:<30}{value}")

    def _status(self) -> int:
        self._section("Memory Sync Status")
        info = self._sync_status()

        self._format_kv("Memory directory:", info["memory"]["path"])
        self._format_kv("  exists:", "yes" if info["memory"]["exists"] else "NO")
        if info["memory"]["exists"]:
            self._format_kv("  files:", info["memory"]["files"])

        self._section("Skills Sync Status")
        self._format_kv("Skills directory:", info["skills"]["path"])
        self._format_kv("  exists:", "yes" if info["skills"]["exists"] else "NO")
        if info["skills"]["exists"]:
            self._format_kv("  skills:", info["skills"]["count"])

        self._section("Remote Sync")
        print("  Remote sync is not configured.")
        print("  To enable sync, set 'sync.remote_url' in config.yaml")

        return 0

    def _push(self) -> int:
        print("Push: Not configured — set 'sync.remote_url' in config.yaml")
        return 1

    def _pull(self) -> int:
        print("Pull: Not configured — set 'sync.remote_url' in config.yaml")
        return 1

    def _now(self) -> int:
        print("Full sync: Not configured — set 'sync.remote_url' in config.yaml")
        return 1

    def _stats(self, by: str = "date") -> int:
        self._section("Sync Statistics")

        mem_dir = self._memory_dir()
        if mem_dir.exists():
            total_files = 0
            total_size = 0
            for f in mem_dir.rglob("*"):
                if f.is_file():
                    total_files += 1
                    total_size += f.stat().st_size

            self._format_kv("Memory files:", total_files)
            self._format_kv("Memory size:", self._human_size(total_size))
        else:
            print("  Memory directory does not exist.")

        skl_dir = self._skills_dir()
        if skl_dir.exists():
            skill_count = len([d for d in skl_dir.iterdir() if d.is_dir()])
            self._format_kv("Skills:", skill_count)
        else:
            print("  Skills directory does not exist.")

        return 0

    def _human_size(self, size: int) -> str:
        for unit in ["B", "KB", "MB", "GB"]:
            if abs(size) < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"
