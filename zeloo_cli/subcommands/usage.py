"""Zeloo usage subcommand — token & cost reporting.

Borrowed from the previous inline ``_cmd_usage`` in ``cli.py``; the
class-based form lets the subcommands framework discover / dispatch
it alongside the rest.
"""

from __future__ import annotations

import argparse

from zeloo_cli.subcommands import Subcommand, subcommand


@subcommand("usage")
class UsageCmd(Subcommand):
    name = "usage"
    help = "Show API usage and cost reports"

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        sub = parser.add_subparsers(dest="usage_action", help="Usage report type")
        sub.add_parser("total", help="Total usage across all sessions")
        sub.add_parser("platform", help="Usage grouped by platform")
        session_p = sub.add_parser("session", help="Usage for a specific session")
        session_p.add_argument("session_id", help="Session ID")

    def run(self, args: argparse.Namespace) -> int:
        action = getattr(args, "usage_action", None)

        try:
            from zeloo_state.usage import UsageTracker
        except Exception as exc:  # noqa: BLE001
            print(f"Error: {exc}")
            return 1

        try:
            tracker = UsageTracker()
        except Exception as exc:  # noqa: BLE001
            print(f"Error: {exc}")
            return 1

        if action == "total":
            return self._total(tracker)
        if action == "platform":
            return self._platform(tracker)
        if action == "session":
            return self._session(tracker, args.session_id)

        print("Usage: Zeloo usage [total|platform|session <session_id>]")
        return 1

    @staticmethod
    def _total(tracker) -> int:
        total = tracker.get_total_usage()
        print("Total API usage:")
        print(f"  Calls:        {total['calls']}")
        print(f"  Input tokens: {total.get('total_in', 0):,}")
        print(f"  Output tokens: {total.get('total_out', 0):,}")
        print(f"  Total tokens: {total['total_tokens']:,}")
        print(f"  Estimated cost: ${total['total_cost']:.6f}")
        return 0

    @staticmethod
    def _platform(tracker) -> int:
        result = tracker.get_platform_usage()
        rows = result.get("breakdown", [])
        if not rows:
            print("No usage data.")
            return 0
        print(f"Usage by platform ({len(rows)} entries):")
        for r in rows:
            print(
                f"  {r['platform']:<12} {r['model']:<30} "
                f"{r['calls']:>5} calls  "
                f"${r['total_cost']:.6f}"
            )
        return 0

    @staticmethod
    def _session(tracker, session_id: str) -> int:
        result = tracker.get_session_usage(session_id)
        print(f"Usage for session {session_id}:")
        print(f"  Total tokens: {result['total_tokens']:,}")
        print(f"  Total cost:   ${result['total_cost']:.6f}")
        print(f"  API calls:    {len(result['calls'])}")
        return 0