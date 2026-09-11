"""Trajectory compression — reduce storage cost of long conversation traces.

Long trajectories are compressed before being persisted to disk or exported
for training. The compression strategy keeps the first and last turns
verbatim (user intent + final result) and summarizes the middle turns.

This module provides pure functions; it does not touch the database directly.
Callers (e.g. ``TurnFinalizer`` or ``datagen.extract_trajectories``) are
responsible for loading raw turns and storing the compressed output.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping
from typing import Any

logger = logging.getLogger(__name__)

# Default thresholds
DEFAULT_MAX_TURNS_FULL = 4  # keep this many turns verbatim (head + tail)
DEFAULT_MAX_CHARS_PER_TURN = 4000  # hard cap on a single turn's serialized size


def compress_trajectory(
    turns: list[dict[str, Any]],
    *,
    max_turns_full: int = DEFAULT_MAX_TURNS_FULL,
    max_chars_per_turn: int = DEFAULT_MAX_CHARS_PER_TURN,
) -> dict[str, Any]:
    """Compress a list of turn dicts into a compact structure.

    Args:
        turns: Ordered list of turn records. Each turn is a dict that may
               contain keys like ``session_id``, ``turn_id``, ``user_message``,
               ``assistant_response``, ``tool_calls``, ``tool_results``,
               ``success``, ``error``.
        max_turns_full: Number of turns to keep verbatim. ``max_turns_full // 2``
                        from the head and the rest from the tail.
        max_chars_per_turn: Hard character cap on the serialized JSON of a
                            single full turn. Content beyond this is truncated.

    Returns:
        A dict with keys ``first_turn``, ``last_turn``, ``middle_summary``
        (a dict with ``turn_count`` and ``condensed`` list), and ``stats``.
        If there are no turns, returns an empty-structure dict.
    """
    if not turns:
        return {
            "first_turn": None,
            "last_turn": None,
            "middle_summary": {"turn_count": 0, "condensed": []},
            "stats": {"input_turns": 0, "kept_full": 0, "compressed": True},
        }

    n = len(turns)
    head_count = max(1, max_turns_full // 2)
    tail_count = max(1, max_turns_full - head_count)

    first_turn = _truncate_turn(turns[0], max_chars_per_turn)

    if n == 1:
        return {
            "first_turn": first_turn,
            "last_turn": first_turn,
            "middle_summary": {"turn_count": 0, "condensed": []},
            "stats": {"input_turns": n, "kept_full": 1, "compressed": False},
        }

    last_turn = _truncate_turn(turns[-1], max_chars_per_turn)

    # Middle turns: keep turn_id + success flag + a short content preview
    middle_start = head_count
    middle_end = n - tail_count
    condensed: list[dict[str, Any]] = []
    for turn in turns[middle_start:middle_end]:
        condensed.append({
            "turn_id": turn.get("turn_id"),
            "success": turn.get("success"),
            "error": turn.get("error"),
            "tool_call_count": _safe_len(turn.get("tool_calls")),
            "user_preview": _preview(turn.get("user_message"), 200),
            "assistant_preview": _preview(turn.get("assistant_response"), 400),
        })

    kept_full = min(n, head_count + tail_count)
    return {
        "first_turn": first_turn,
        "last_turn": last_turn,
        "middle_summary": {
            "turn_count": len(condensed),
            "condensed": condensed,
        },
        "stats": {
            "input_turns": n,
            "kept_full": kept_full,
            "compressed": n > kept_full,
        },
    }


def compress_session_turns(
    turns: Iterable[Mapping[str, Any]],
    **kwargs: Any,
) -> dict[str, Any]:
    """Convenience wrapper that accepts any iterable of turn mappings."""
    return compress_trajectory([dict(t) for t in turns], **kwargs)


# ── Internal helpers ────────────────────────────────────────────────

def _truncate_turn(turn: dict[str, Any], max_chars: int) -> dict[str, Any]:
    """Return a copy of *turn* with long string fields truncated."""
    serialized = json.dumps(turn, ensure_ascii=False, default=str)
    if len(serialized) <= max_chars:
        return turn

    # Truncate large string fields instead of dropping the whole turn
    result: dict[str, Any] = {}
    for key, value in turn.items():
        if isinstance(value, str) and len(value) > max_chars:
            result[key] = value[:max_chars] + "...[truncated]"
        else:
            result[key] = value
    return result


def _preview(text: Any, max_chars: int) -> str:
    """Return a short preview of *text* for the condensed middle section."""
    if text is None:
        return ""
    s = str(text)
    if len(s) <= max_chars:
        return s
    return s[:max_chars] + "..."


def _safe_len(value: Any) -> int:
    """Return len(value) if it's sized, else 0."""
    try:
        return len(value)  # type: ignore[arg-type]
    except TypeError:
        return 0
