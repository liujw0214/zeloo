"""Zeloo logs subcommand — log viewing and management.

Provides viewing, tailing, and clearing of logs from ~/.Zeloo/logs/.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from zeloo_cli.subcommands import Subcommand, subcommand


@subcommand("logs")
class LogsCmd(Subcommand):
    name = "logs"
    help = "View, tail, or clear Zeloo logs"

    _LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--lines", "-n", type=int, default=100,
            help="Number of lines to show (default: 100)",
        )
        parser.add_argument(
            "--level", "-l", choices=cls._LOG_LEVELS, default=None,
            help="Filter by log level",
        )
        sub = parser.add_subparsers(dest="logs_action", help="Logs action")

        tail_p = sub.add_parser("tail", help="Follow log output in real-time")
        tail_p.add_argument(
            "--lines", "-n", type=int, default=50,
            help="Lines to show before tailing (default: 50)",
        )
        tail_p.add_argument(
            "--level", "-l", choices=cls._LOG_LEVELS, default=None,
            help="Filter by log level",
        )

        clear_p = sub.add_parser("clear", help="Clear all log files")
        clear_p.add_argument(
            "--force", action="store_true",
            help="Skip confirmation prompt",
        )

        sub.add_parser("list", help="List available log files")

    def run(self, args: argparse.Namespace) -> int:
        action = getattr(args, "logs_action", None)

        if action == "tail":
            return self._tail(args.lines, args.level)
        if action == "clear":
            return self._clear(args.force)
        if action == "list":
            return self._list_logs()

        return self._view(args.lines, args.level)

    def _get_log_dir(self) -> Path:
        env_home = os.environ.get("ZELOO_HOME", "").strip()
        if env_home:
            log_dir = Path(env_home) / "logs"
        elif sys.platform == "win32":
            local = os.environ.get("LOCALAPPDATA", "").strip()
            base = Path(local) if local else Path.home() / "AppData" / "Local"
            log_dir = base / "Zeloo" / "logs"
        else:
            log_dir = Path.home() / ".Zeloo" / "logs"
        return log_dir

    def _list_log_files(self) -> list[Path]:
        log_dir = self._get_log_dir()
        if not log_dir.exists():
            return []
        pattern = "*.log" if log_dir.glob("*.log") else "*"
        files = sorted(log_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        return files

    def _list_logs(self) -> int:
        files = self._list_log_files()
        if not files:
            print(f"No log files found in {self._get_log_dir()}")
            return 0

        print(f"Log files in {self._get_log_dir()}:")
        print("-" * 60)
        for f in files:
            size = f.stat().st_size
            if size < 1024:
                size_str = f"{size} B"
            elif size < 1024 * 1024:
                size_str = f"{size / 1024:.1f} KB"
            else:
                size_str = f"{size / (1024 * 1024):.1f} MB"
            mtime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(f.stat().st_mtime))
            print(f"  {f.name:<40} {size_str:>10}  {mtime}")
        return 0

    def _view(self, lines: int, level: str | None) -> int:
        log_dir = self._get_log_dir()
        if not log_dir.exists():
            print(f"Log directory not found: {log_dir}")
            return 1

        log_files = self._list_log_files()
        if not log_files:
            print("No log files found.")
            return 0

        main_log = log_files[0]
        try:
            with open(main_log, encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
        except Exception as exc:
            print(f"Failed to read log file: {exc}")
            return 1

        if level:
            filtered = [l for l in all_lines if level in l]
        else:
            filtered = all_lines

        display_lines = filtered[-lines:] if len(filtered) > lines else filtered

        for line in display_lines:
            print(line.rstrip())
        return 0

    def _tail(self, lines: int, level: str | None) -> int:
        log_dir = self._get_log_dir()
        if not log_dir.exists():
            print(f"Log directory not found: {log_dir}")
            return 1

        log_files = self._list_log_files()
        if not log_files:
            print("No log files found.")
            return 0

        main_log = log_files[0]
        print(f"Tailing {main_log} (Ctrl+C to stop)...")
        print("-" * 60)

        try:
            with open(main_log, encoding="utf-8", errors="replace") as f:
                f.seek(0, os.SEEK_END)

                initial_lines = []
                for _ in range(lines):
                    line = f.readline()
                    if not line:
                        break
                    initial_lines.append(line)

                for line in initial_lines[-lines:]:
                    if level is None or level in line:
                        print(line.rstrip())

                while True:
                    line = f.readline()
                    if not line:
                        time.sleep(0.5)
                        continue
                    if level is None or level in line:
                        print(line.rstrip())
        except KeyboardInterrupt:
            print("\nStopped.")
        except Exception as exc:
            print(f"Tail error: {exc}")
            return 1
        return 0

    def _clear(self, force: bool) -> int:
        log_dir = self._get_log_dir()
        if not log_dir.exists():
            print(f"Log directory not found: {log_dir}")
            return 0

        log_files = self._list_log_files()
        if not log_files:
            print("No log files to clear.")
            return 0

        if not force:
            confirm = input(f"Clear {len(log_files)} log file(s) in {log_dir}? [y/N] ")
            if confirm.lower() != "y":
                print("Cancelled.")
                return 0

        cleared = 0
        for f in log_files:
            try:
                f.unlink()
                cleared += 1
            except Exception as exc:
                print(f"Failed to delete {f.name}: {exc}")

        print(f"Cleared {cleared} log file(s).")
        return 0
