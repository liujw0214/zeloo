"""Zeloo dump subcommand — data export utilities."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from zeloo_cli.subcommands import Subcommand, subcommand


@subcommand("dump")
class DumpCmd(Subcommand):
    name = "dump"
    help = "Export sessions, memories or config to file"

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        sub = parser.add_subparsers(dest="dump_action", help="Export type")

        sessions_p = sub.add_parser("sessions", help="Export all sessions to JSON")
        sessions_p.add_argument("--output", "-o", type=Path, default=None, help="Output file path")

        memories_p = sub.add_parser("memories", help="Export all memories to JSON")
        memories_p.add_argument("--output", "-o", type=Path, default=None, help="Output file path")

        config_p = sub.add_parser("config", help="Export configuration to YAML")
        config_p.add_argument("--output", "-o", type=Path, default=None, help="Output file path")

    def run(self, args: argparse.Namespace) -> int:
        action = getattr(args, "dump_action", None)

        if action == "sessions":
            return self._dump_sessions(args.output)
        if action == "memories":
            return self._dump_memories(args.output)
        if action == "config":
            return self._dump_config(args.output)

        print("Usage: Zeloo dump [sessions|memories|config]")
        return 1

    def _get_zeloo_home(self) -> Path:
        from agent.zeloo_constants import get_zeloo_home
        return get_zeloo_home()

    def _dump_sessions(self, output: Path | None) -> int:
        try:
            from zeloo_state import SessionDB

            db = SessionDB()
            sessions = db.list_sessions(limit=10000)

            export_data = {
                "exported_at": self._timestamp(),
                "session_count": len(sessions),
                "sessions": sessions,
            }

            out_path = output or Path("sessions_export.json")
            self._write_json(out_path, export_data)
            print(f"Exported {len(sessions)} sessions to: {out_path}")
            return 0

        except Exception as exc:
            print(f"Export failed: {exc}")
            return 1

    def _dump_memories(self, output: Path | None) -> int:
        memories_dir = self._get_zeloo_home() / "memories"
        if not memories_dir.exists():
            print("(no memories directory found)")
            return 0

        memories = []
        for md_file in memories_dir.rglob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8")
                memories.append({
                    "file": str(md_file.relative_to(memories_dir)),
                    "content": content,
                })
            except Exception:
                pass

        export_data = {
            "exported_at": self._timestamp(),
            "memory_count": len(memories),
            "memories": memories,
        }

        out_path = output or Path("memories_export.json")
        self._write_json(out_path, export_data)
        print(f"Exported {len(memories)} memories to: {out_path}")
        return 0

    def _dump_config(self, output: Path | None) -> int:
        import yaml

        config_path = self._get_zeloo_home() / "config.yaml"
        if not config_path.exists():
            print("(no config file found)")
            return 1

        try:
            with open(config_path, encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}

            out_path = output or Path("config_export.yaml")
            with open(out_path, "w", encoding="utf-8") as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

            print(f"Exported config to: {out_path}")
            return 0

        except Exception as exc:
            print(f"Export failed: {exc}")
            return 1

    def _write_json(self, path: Path, data: dict) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _timestamp(self) -> str:
        from datetime import datetime
        return datetime.now().isoformat()
