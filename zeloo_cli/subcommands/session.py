"""Zeloo session subcommand — session management."""

from __future__ import annotations

import argparse
from pathlib import Path

from zeloo_cli.subcommands import Subcommand, subcommand


@subcommand("session")
class SessionCmd(Subcommand):
    name = "session"
    help = "Manage Zeloo sessions (list, export, delete)"

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        sub = parser.add_subparsers(dest="session_action", help="Session action")

        list_p = sub.add_parser("list", help="List recent sessions")
        list_p.add_argument("--limit", type=int, default=20, help="Max sessions to show")

        export_p = sub.add_parser("export", help="Export a session to JSONL")
        export_p.add_argument("session_id", help="Session ID to export")
        export_p.add_argument("--output", "-o", type=Path, default=None, help="Output file path")

        delete_p = sub.add_parser("delete", help="Delete a session")
        delete_p.add_argument("session_id", help="Session ID to delete")
        delete_p.add_argument("--force", action="store_true", help="Skip confirmation")

    def run(self, args: argparse.Namespace) -> int:
        action = getattr(args, "session_action", None)
        if action == "list":
            return self._list(args.limit)
        if action == "export":
            return self._export(args.session_id, args.output)
        if action == "delete":
            return self._delete(args.session_id, args.force)
        print("Usage: Zeloo session [list|export|delete]")
        return 1

    def _list(self, limit: int) -> int:
        from zeloo_state import SessionDB

        try:
            db = SessionDB()
            sessions = db.list_sessions(limit=limit)
        except Exception as exc:
            print(f"Error: {exc}")
            return 1

        if not sessions:
            print("No sessions found.")
            return 0

        # Rich-rendered table (Hermes Agent parity).
        from zeloo_cli.rich_render import make_console, make_table

        console = make_console()
        table = make_table(
            title=f"Recent sessions ({len(sessions)})",
            columns=[
                ("SESSION ID", "bold cyan"),
                ("PLATFORM", "yellow"),
                ("CREATED", "green"),
                ("MESSAGES", "magenta"),
            ],
        )
        for s in sessions:
            table.add_row(
                s.get("session_id", "?")[:36],
                s.get("platform", "?")[:8],
                s.get("created_at", "?")[:24],
                str(s.get("message_count", 0)),
            )
        console.print(table)
        return 0

    def _export(self, session_id: str, output: Path | None) -> int:
        from zeloo_state import SessionDB
        from zeloo_state_messages import MessageExporter

        try:
            db = SessionDB()
            sess = db.get_session(session_id)
            if sess is None:
                print(f"Session not found: {session_id}")
                return 1

            exporter = MessageExporter(db.db_path)
            out_path = exporter.export_session(session_id, output_path=output)
            print(f"Exported to: {out_path}")
            return 0
        except Exception as exc:
            print(f"Export failed: {exc}")
            return 1

    def _delete(self, session_id: str, force: bool) -> int:
        from zeloo_state import SessionDB

        if not force:
            confirm = input(f"Delete session {session_id}? [y/N] ")
            if confirm.lower() != "y":
                print("Cancelled.")
                return 0

        try:
            db = SessionDB()
            conn = db._conn
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM trajectories WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            conn.commit()
            print(f"Deleted session: {session_id}")
            return 0
        except Exception as exc:
            print(f"Delete failed: {exc}")
            return 1
