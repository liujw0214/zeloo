"""``Zeloo group-chat`` subcommand.

Lets operators (and downstream tools: cron, webhook, kanban) drive the same
multi-agent fan-out that the dashboard /chat Group tab uses, from the CLI:

    Zeloo group-chat send \\
        --host coder \\
        --workers researcher,coder \\
        --prompt "分析 docker 为什么比 VM 启动快"

Output: the synthesized host reply on stdout (just like ``Zeloo -z``), with a
worker trail in stderr when ``--verbose``. ``--json`` emits the full
``GroupChatResult`` envelope for machine consumption.

The actual fan-out logic lives in ``zeloo_cli.group_chat_lib`` — this module
is a thin argparse adapter that lets background callers (cron scheduler,
webhook dispatcher, kanban task) bypass the dashboard entirely.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional, Sequence

from zeloo_cli.group_chat_lib import (
    GroupChatError,
    GroupChatResult,
    MAX_WORKERS,
    run_group_chat_fan_out_sync,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="Zeloo group-chat",
        description=(
            "Multi-agent fan-out: ask one or more worker profiles in parallel, "
            "then synthesize a final reply through a host profile. Mirrors the "
            "dashboard /chat Group tab so cron, webhook and kanban can reuse the "
            "same flow without a browser."
        ),
    )
    sub = parser.add_subparsers(dest="group_chat_command", required=True)

    send_p = sub.add_parser(
        "send",
        help="Run one fan-out and print the synthesized host reply",
        description=(
            "Spawn one Zeloo subprocess per worker profile in parallel, then ask "
            "the host profile to integrate the worker outputs. The host reply is "
            "printed on stdout (or emitted as JSON when --json)."
        ),
    )
    send_p.add_argument(
        "--host", required=True,
        help="Profile name that produces the final synthesized reply",
    )
    send_p.add_argument(
        "--workers", required=True,
        help=(
            "Comma-separated worker profile names (1..%d). Each runs in parallel "
            "with the user prompt; the host sees all worker outputs and integrates them."
        ) % MAX_WORKERS,
    )
    send_p.add_argument(
        "--prompt", required=True,
        help="The natural-language question / task to send to every worker (and to the host).",
    )
    send_p.add_argument(
        "--timeout", type=int, default=180,
        help="Per-profile subprocess timeout in seconds (10..900). Default 180.",
    )
    send_p.add_argument(
        "--json", dest="as_json", action="store_true",
        help="Emit the full GroupChatResult envelope as JSON on stdout (instead of just the host reply).",
    )
    send_p.add_argument(
        "--verbose", "-v", action="store_true",
        help="Print the per-worker trail to stderr as they finish.",
    )

    return parser


def _split_workers(raw: str) -> list[str]:
    return [w.strip() for w in raw.split(",") if w.strip()]


def cmd_group_chat_send(args: argparse.Namespace) -> int:
    workers = _split_workers(args.workers)
    if not workers:
        print("--workers must list at least one profile", file=sys.stderr)
        return 2

    try:
        result: GroupChatResult = run_group_chat_fan_out_sync(
            prompt=args.prompt,
            host=args.host,
            workers=workers,
            timeout_s=args.timeout,
        )
    except GroupChatError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.verbose:
        for w in result.workers:
            marker = "OK " if w.ok else "ERR"
            print(
                f"  [{marker}] {w.name} ({w.elapsed_s}s): "
                f"{(w.output or w.error or '')[:200].replace(chr(10), ' ')}",
                file=sys.stderr,
            )

    if args.as_json:
        json.dump(result.to_dict(), sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(result.host_output)
        if not result.host_output.endswith("\n"):
            sys.stdout.write("\n")

    return 0 if result.ok else 1


def cmd_group_chat(args: argparse.Namespace) -> int:
    sub = getattr(args, "group_chat_command", None)
    if sub == "send":
        return cmd_group_chat_send(args)
    print("Usage: Zeloo group-chat send --host <p> --workers a,b --prompt '...'", file=sys.stderr)
    return 2


def register_group_chat_subparser(subparsers) -> argparse.ArgumentParser:
    """Attach ``Zeloo group-chat`` to the top-level subparser tree.

    Used by ``zeloo_cli.main.build_subparsers``. Sets ``func`` so the
    ``_forward_command`` shim knows which handler to call.
    """
    parser = subparsers.add_parser(
        "group-chat",
        help=(
            "Multi-agent fan-out: ask one or more worker profiles in parallel, "
            "then synthesize a final reply through a host profile."
        ),
        description=(
            "Mirrors the dashboard /chat Group tab so cron, webhook and kanban "
            "can reuse the same flow without a browser. See `Zeloo group-chat "
            "send --help` for the per-subcommand options."
        ),
    )
    send_p = parser.add_subparsers(dest="group_chat_command", required=True).add_parser(
        "send",
        help="Run one fan-out and print the synthesized host reply",
        description=(
            "Spawn one Zeloo subprocess per worker profile in parallel, then ask "
            "the host profile to integrate the worker outputs. The host reply is "
            "printed on stdout (or emitted as JSON when --json)."
        ),
    )
    send_p.add_argument(
        "--host", required=True,
        help="Profile name that produces the final synthesized reply",
    )
    send_p.add_argument(
        "--workers", required=True,
        help=(
            "Comma-separated worker profile names (1..%d). Each runs in parallel "
            "with the user prompt; the host sees all worker outputs and integrates them."
        ) % MAX_WORKERS,
    )
    send_p.add_argument(
        "--prompt", required=True,
        help="The natural-language question / task to send to every worker (and to the host).",
    )
    send_p.add_argument(
        "--timeout", type=int, default=180,
        help="Per-profile subprocess timeout in seconds (10..900). Default 180.",
    )
    send_p.add_argument(
        "--json", dest="as_json", action="store_true",
        help="Emit the full GroupChatResult envelope as JSON on stdout (instead of just the host reply).",
    )
    send_p.add_argument(
        "--verbose", "-v", action="store_true",
        help="Print the per-worker trail to stderr as they finish.",
    )
    parser.set_defaults(func=cmd_group_chat)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Stand-alone entry point for ``python -m zeloo_cli.group_chat_cmd``."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return cmd_group_chat(args)


if __name__ == "__main__":
    sys.exit(main())