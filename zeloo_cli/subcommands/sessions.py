"""Zeloo sessions subcommand — session management with platform filter.

Provides list, show, delete, and search operations for session history.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from zeloo_cli.subcommands import Subcommand, subcommand


@subcommand("sessions")
class SessionsCmd(Subcommand):
    name = "sessions"
    help = "Manage session history (list, show, delete, search)"

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        sub = parser.add_subparsers(dest="sessions_action", help="Sessions action")

        list_p = sub.add_parser("list", help="List recent sessions")
        list_p.add_argument(
            "--limit", "-n", type=int, default=20,
            help="Max sessions to show (default: 20)",
        )
        list_p.add_argument(
            "--platform", choices=["cli", "gateway"], default=None,
            help="Filter by platform (cli or gateway)",
        )

        show_p = sub.add_parser("show", help="Show session details")
        show_p.add_argument("session_id", help="Session ID to display")

        delete_p = sub.add_parser("delete", help="Delete a session")
        delete_p.add_argument("session_id", help="Session ID to delete")
        delete_p.add_argument(
            "--force", action="store_true",
            help="Skip confirmation prompt",
        )

        search_p = sub.add_parser("search", help="Search session messages")
        search_p.add_argument("query", help="Search query text")
        search_p.add_argument(
            "--limit", "-n", type=int, default=20,
            help="Max results to show (default: 20)",
        )

    def run(self, args: argparse.Namespace) -> int:
        action = getattr(args, "sessions_action", None)
        if action == "list":
            return self._list(
                getattr(args, "limit", 20),
                getattr(args, "platform", None),
            )
        if action == "show":
            return self._show(args.session_id)
        if action == "delete":
            return self._delete(args.session_id, getattr(args, "force", False))
        if action == "search":
            return self._search(
                args.query,
                getattr(args, "limit", 20),
            )
        print("Usage: zeloo sessions [list|show|delete|search]")
        return 1

    def _list(self, limit: int, platform: str | None) -> int:
        try:
            from zeloo_state import SessionDB
        except Exception as exc:
            print(f"Error: {exc}")
            return 1

        try:
            db = SessionDB()
            sessions = db.list_sessions(limit=limit)
        except Exception as exc:
            print(f"Failed to load sessions: {exc}")
            return 1

        if platform:
            sessions = [s for s in sessions if s.get("platform") == platform]

        if not sessions:
            print("No sessions found.")
            return 0

        try:
            from zeloo_cli.rich_render import make_console, make_table
            console = make_console()
            table = make_table(
                title=f"Sessions ({len(sessions)})",
                columns=[
                    ("SESSION ID", "bold cyan"),
                    ("PLATFORM", "yellow"),
                    ("CREATED", "green"),
                    ("UPDATED", "blue"),
                    ("MESSAGES", "magenta"),
                ],
            )
            for s in sessions:
                table.add_row(
                    s.get("session_id", "?")[:36],
                    s.get("platform", "?")[:10],
                    s.get("created_at", "?")[:19],
                    s.get("updated_at", "?")[:19],
                    str(s.get("message_count", 0)),
                )
            console.print(table)
        except Exception:
            print(f"{'SESSION ID':<36} {'PLATFORM':<10} {'CREATED':<19} {'UPDATED':<19} {'MSGS':>5}")
            print("-" * 90)
            for s in sessions:
                print(
                    f"{s.get('session_id', '?')[:36]:<36} "
                    f"{s.get('platform', '?')[:10]:<10} "
                    f"{s.get('created_at', '?')[:19]:<19} "
                    f"{s.get('updated_at', '?')[:19]:<19} "
                    f"{s.get('message_count', 0):>5}"
                )
        return 0

    def _show(self, session_id: str) -> int:
        try:
            from zeloo_state import SessionDB
        except Exception as exc:
            print(f"Error: {exc}")
            return 1

        try:
            db = SessionDB()
            session = db.get_session(session_id)
            if session is None:
                print(f"Session not found: {session_id}")
                return 1

            messages = db.get_messages(session_id)
        except Exception as exc:
            print(f"Failed to load session: {exc}")
            return 1

        print(f"Session: {session_id}")
        print("=" * 60)
        print(f"  Platform:    {session.get('platform', '?')}")
        print(f"  User ID:    {session.get('user_id', '')}")
        print(f"  Created:    {session.get('created_at', '?')}")
        print(f"  Updated:    {session.get('updated_at', '?')}")
        print(f"  Messages:   {len(messages)}")

        if messages:
            print("\nRecent messages:")
            print("-" * 60)
            for msg in messages[-10:]:
                role = msg.get("role", "?")
                content = msg.get("content", "")
                if content:
                    preview = content[:100] + "..." if len(content) > 100 else content
                    print(f"  [{role:>8}] {preview}")
        return 0

    def _delete(self, session_id: str, force: bool) -> int:
        try:
            from zeloo_state import SessionDB
        except Exception as exc:
            print(f"Error: {exc}")
            return 1

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

    def _search(self, query: str, limit: int) -> int:
        try:
            from zeloo_state import SessionDB
        except Exception as exc:
            print(f"Error: {exc}")
            return 1

        try:
            db = SessionDB()
            sessions = db.list_sessions(limit=100)
        except Exception as exc:
            print(f"Failed to search sessions: {exc}")
            return 1

        query_lower = query.lower()
        results: list[dict[str, Any]] = []

        for session in sessions:
            sid = session.get("session_id", "")
            messages = db.get_messages(sid, limit=50)
            for msg in messages:
                content = msg.get("content", "")
                if content and query_lower in content.lower():
                    results.append({
                        "session_id": sid,
                        "role": msg.get("role", "?"),
                        "preview": content[:150],
                    })
                    break

            if len(results) >= limit:
                break

        if not results:
            print(f"No sessions found matching: {query}")
            return 0

        print(f"Found {len(results)} sessions matching: {query}")
        print("-" * 60)
        for r in results:
            print(f"Session: {r['session_id'][:36]}")
            print(f"  [{r['role']:>8}] {r['preview'][:100]}...")
            print()
        return 0
