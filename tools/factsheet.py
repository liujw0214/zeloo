"""Single-agent factsheet — structured key-value memory for cross-session continuity.

Audit 2026-09-17 / Design: docs/design/agent-self-improvement-mvp-fit-2026-09-17.md

The single-agent reuse of the M2 hosted_room factsheet concept. Lives at
``<zeloo_home>/workspace/FACTSHEET.json``. Writes are atomic; reads tolerate
a missing or corrupt file (return empty dict). Confidence levels are part
of the schema so callers can decide whether to trust an entry.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any, Literal

from zeloo_constants import get_zeloo_home as _get_zeloo_home_fn

logger = logging.getLogger(__name__)

Confidence = Literal["verified", "high", "low"]


def _factsheet_path() -> Path:
    """Path to the workspace factsheet JSON file.

    Looks up ``get_zeloo_home`` lazily so monkeypatching it in tests works.
    """
    return _get_zeloo_home_fn() / "workspace" / "FACTSHEET.json"


def _read_raw(path: Path) -> dict[str, Any]:
    """Read raw JSON from ``path``; return ``{}`` on missing/corrupt/empty."""
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        logger.warning("Could not read factsheet %s: %s", path, exc)
        return {}
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("Corrupt factsheet %s: %s — treating as empty", path, exc)
        return {}
    if not isinstance(data, dict):
        logger.warning(
            "Factsheet %s is not a dict (got %s) — treating as empty",
            path, type(data).__name__,
        )
        return {}
    return data


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    """Write JSON to ``path`` atomically (tmp + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=".factsheet-", suffix=".json.tmp", dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        with suppress(Exception):
            os.unlink(tmp_path)
        raise


def read_factsheet() -> dict[str, Any]:
    """Return the full factsheet as a dict. Empty dict if file is missing/corrupt."""
    return _read_raw(_factsheet_path())


def get(key: str, default: Any = None) -> Any:
    """Return the value for ``key``, or ``default`` if absent."""
    return read_factsheet().get(key, default)


def set_entry(
    key: str,
    value: Any,
    *,
    confidence: Confidence = "high",
    sources: list[str] | None = None,
    note: str | None = None,
) -> None:
    """Set (or overwrite) a factsheet entry.

    ``sources`` are file paths that back the claim (audit report, patch file,
    commit SHA). ``note`` is a one-line explanation visible to future readers.
    """
    path = _factsheet_path()
    data = _read_raw(path)
    data[key] = {
        "value": value,
        "confidence": confidence,
        "sources": sources or [],
        "last_updated": _today_iso(),
    }
    if note is not None:
        data[key]["note"] = note
    _atomic_write(path, data)


def merge_entry(
    key: str,
    *,
    confidence: Confidence | None = None,
    sources: list[str] | None = None,
    note: str | None = None,
) -> None:
    """Update metadata of an existing entry without changing its value.

    Silently no-ops if ``key`` does not exist (use ``set_entry`` for new keys).
    Confidence can only move UP the ladder: ``low`` → ``high`` → ``verified``.
    Sources are merged (deduped, append-only).
    """
    ladder = {"low": 0, "high": 1, "verified": 2}
    path = _factsheet_path()
    data = _read_raw(path)
    if key not in data or not isinstance(data[key], dict):
        return
    entry = data[key]
    if confidence is not None:
        current_rank = ladder.get(entry.get("confidence", "low"), 0)
        new_rank = ladder.get(confidence, 0)
        if new_rank > current_rank:
            entry["confidence"] = confidence
    if sources:
        merged = list(entry.get("sources", []))
        for s in sources:
            if s not in merged:
                merged.append(s)
        entry["sources"] = merged
    if note is not None:
        existing_note = entry.get("note", "")
        if note not in existing_note:
            entry["note"] = (existing_note + "; " + note).strip("; ")
    entry["last_updated"] = _today_iso()
    _atomic_write(path, data)


def render_summary(max_entries: int = 20) -> str:
    """Render a compact Markdown summary suitable for prompt injection.

    Empty string if no entries. Sorted by confidence (verified first), then
    by last_updated descending.
    """
    data = read_factsheet()
    if not data:
        return ""

    ladder = {"verified": 0, "high": 1, "low": 2}

    def sort_key(item):
        k, v = item
        if not isinstance(v, dict):
            return (3, "")
        conf = ladder.get(v.get("confidence", "low"), 2)
        return (conf, "-" + str(v.get("last_updated", "")))

    sorted_items = sorted(data.items(), key=sort_key)
    lines = ["## Factsheet (cross-session memory)"]
    for k, v in sorted_items[:max_entries]:
        if not isinstance(v, dict):
            lines.append(f"- **{k}** = {v!r}")
            continue
        val = v.get("value")
        conf = v.get("confidence", "?")
        conf_marker = {"verified": "[✓]", "high": "[~]", "low": "[?]"}.get(conf, "[?]")
        # Truncate value for prompt injection
        val_repr = repr(val)
        if len(val_repr) > 200:
            val_repr = val_repr[:197] + "..."
        lines.append(f"- {conf_marker} **{k}** = {val_repr}")
    return "\n".join(lines)


def _today_iso() -> str:
    """ISO date for ``last_updated`` fields."""
    from datetime import date
    return date.today().isoformat()