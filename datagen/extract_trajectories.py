"""Export stored trajectories as ShareGPT-format training data.

Reads turn trajectories from ``~/.Zeloo/state.db`` (or a custom DB path),
groups them by session, optionally compresses long sessions via
:mod:`datagen.compress_trajectories`, and writes one JSON object per session to
stdout or a file.

Usage::

    python -m datagen.extract_trajectories --output data.jsonl
    python -m datagen.extract_trajectories --db /path/to/state.db --no-compress
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

# Allow running from project root without installation
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datagen.compress_trajectories import compress_trajectory  # noqa: E402


def _default_db_path() -> Path:
    """Return the default state.db location under ~/.Zeloo/."""
    zeloo_home = Path.home() / ".Zeloo"
    return zeloo_home / "state.db"


def load_trajectories(db_path: Path) -> dict[str, list[dict[str, Any]]]:
    """Load all trajectories from the DB, grouped by session_id.

    Returns a mapping of ``session_id -> ordered list of turn dicts``
    (sorted by turn_id).
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT session_id, turn_id, data FROM trajectories ORDER BY session_id, turn_id"
        ).fetchall()
    finally:
        conn.close()

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        try:
            data = json.loads(row["data"])
        except json.JSONDecodeError:
            continue
        data.setdefault("turn_id", row["turn_id"])
        grouped[row["session_id"]].append(data)

    return dict(grouped)


def turn_to_sharegpt(turn: dict[str, Any]) -> list[dict[str, str]]:
    """Convert a single turn dict into a list of ShareGPT conversation turns."""
    conv: list[dict[str, str]] = []

    user_msg = turn.get("user_message")
    if user_msg:
        conv.append({"from": "human", "value": str(user_msg)})

    # Tool calls + results are interleaved as a single gpt turn with tool_calls
    assistant_msg = turn.get("assistant_response") or ""
    tool_calls = turn.get("tool_calls") or []
    tool_results = turn.get("tool_results") or []

    if tool_calls or assistant_msg:
        gpt_turn: dict[str, Any] = {"from": "gpt", "value": str(assistant_msg)}
        if tool_calls:
            gpt_turn["tool_calls"] = tool_calls
        conv.append(gpt_turn)

    if tool_results:
        for result in tool_results:
            if isinstance(result, dict):
                value = result.get("content") or result.get("output") or str(result)
            else:
                value = str(result)
            conv.append({"from": "tool", "value": str(value)})

    return conv


def turn_to_alpaca(turn: dict[str, Any]) -> dict[str, str]:
    """Convert a single turn into an Alpaca instruction-tuning format record.

    Alpaca format: ``{"instruction": str, "input": str, "output": str}``
    For multi-turn sessions the first user/assistant pair becomes the
    instruction/input/output and remaining turns are prepended to the output.
    """
    user_msg = str(turn.get("user_message", ""))
    assistant_msg = str(turn.get("assistant_response", ""))
    tool_results = turn.get("tool_results") or []
    tool_results_str = "\n\n".join(
        _safe_str(r.get("content") or r.get("output") or str(r)) for r in tool_results if r
    )

    instruction = user_msg
    output_parts: list[str] = []
    if assistant_msg:
        output_parts.append(assistant_msg)
    if tool_results_str:
        output_parts.append(f"[Tool results]\n{tool_results_str}")

    return {
        "instruction": instruction,
        "input": "",
        "output": "\n\n".join(output_parts) if output_parts else "",
    }


def session_to_alpaca(
    session_id: str,
    turns: list[dict[str, Any]],
    *,
    compress: bool = True,
) -> dict[str, Any]:
    """Convert a full session's turns into an Alpaca-format record.

    The first turn maps to ``instruction/input/output``.
    Subsequent turns are appended to the output field to preserve context.
    """
    if compress and len(turns) > 4:
        compressed = compress_trajectory(turns)
        turns = []
        ft = compressed.get("first_turn")
        if ft:
            turns.append(ft)
        for m in compressed.get("middle_summary", {}).get("condensed", []):
            turns.append({
                "user_message": m.get("user_preview", ""),
                "assistant_response": m.get("assistant_preview", ""),
            })
        lt = compressed.get("last_turn")
        if lt and lt not in turns:
            turns.append(lt)

    if not turns:
        return {"session_id": session_id, "instruction": "", "input": "", "output": ""}

    first = turns[0]
    result: dict[str, str] = {
        "instruction": str(first.get("user_message", "")),
        "input": "",
        "output": str(first.get("assistant_response", "")),
    }

    for turn in turns[1:]:
        parts: list[str] = []
        if turn.get("user_message"):
            parts.append(f"[User]: {turn['user_message']}")
        if turn.get("assistant_response"):
            parts.append(f"[Assistant]: {turn['assistant_response']}")
        if turn.get("tool_results"):
            for r in turn["tool_results"]:
                parts.append(f"[Tool]: {_safe_str(r.get('content') or r.get('output') or str(r))}")
        if result["output"]:
            result["output"] += "\n\n" + "\n".join(parts)
        else:
            result["output"] = "\n".join(parts)

    result["session_id"] = session_id
    return result


def _safe_str(val: str) -> str:
    if not val:
        return ""
    return val[:2000]


def session_to_sharegpt(
    session_id: str,
    turns: list[dict[str, Any]],
    *,
    compress: bool = True,
) -> dict[str, Any]:
    """Convert a full session's turns into a ShareGPT-format object."""
    if compress and len(turns) > 4:
        compressed = compress_trajectory(turns)
        turns = [t for t in (compressed.get("first_turn"),) if t]
        for m in compressed.get("middle_summary", {}).get("condensed", []):
            turns.append({
                "turn_id": m.get("turn_id"),
                "user_message": m.get("user_preview", ""),
                "assistant_response": m.get("assistant_preview", ""),
                "success": m.get("success"),
            })
        lt = compressed.get("last_turn")
        if lt and lt not in turns:
            turns.append(lt)

    conversations: list[dict[str, str]] = []
    for turn in turns:
        conversations.extend(turn_to_sharegpt(turn))

    return {
        "session_id": session_id,
        "conversations": conversations,
    }


def extract_for_training(
    db_path: Path,
    format: str = "sharegpt",
    *,
    compress: bool = True,
) -> list[dict[str, Any]]:
    """Load all sessions from the database and export in the specified format.

    Args:
        db_path: Path to the state.db file.
        format: One of ``"sharegpt"`` (default), ``"alpaca"``, or ``"jsonl"``
            (raw per-turn JSON objects, no session grouping).
        compress: Whether to apply trajectory compression for long sessions.

    Returns:
        List of training records in the chosen format.
    """
    grouped = load_trajectories(db_path)
    if not grouped:
        return []

    if format == "jsonl":
        records: list[dict[str, Any]] = []
        for sid, turns in grouped.items():
            for turn in turns:
                records.append({"session_id": sid, **turn})
        return records

    if format == "alpaca":
        return [
            session_to_alpaca(sid, turns, compress=compress)
            for sid, turns in grouped.items()
        ]

    return [
        session_to_sharegpt(sid, turns, compress=compress)
        for sid, turns in grouped.items()
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Export trajectories as ShareGPT JSONL")
    parser.add_argument(
        "--db",
        type=Path,
        default=_default_db_path(),
        help="Path to state.db (default: ~/.Zeloo/state.db)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output JSONL file (default: stdout)",
    )
    parser.add_argument(
        "--no-compress",
        action="store_true",
        help="Disable trajectory compression for long sessions",
    )
    parser.add_argument(
        "--format",
        dest="format",
        default="sharegpt",
        choices=["sharegpt", "alpaca", "jsonl"],
        help="Output format: sharegpt (default), alpaca, or jsonl (raw per-turn)",
    )
    args = parser.parse_args()

    if not args.db.exists():
        print(f"Database not found: {args.db}", file=sys.stderr)
        return 1

    compress = not args.no_compress
    records = extract_for_training(args.db, format=args.format, compress=compress)

    out_lines = [json.dumps(r, ensure_ascii=False) for r in records]
    output = "\n".join(out_lines) + "\n"

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
        print(f"Exported {len(records)} session(s) to {args.output}")
    else:
        sys.stdout.write(output)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
