"""Curator — skill lifecycle management system.

This module manages the
lifecycle of skills through a state machine:

    active ──(not used for N days)──► stale ──(not used for M days)──► archived

Key principles:
- Skills are NEVER deleted, only archived (recoverable).
- The curator runs as a background task that tracks skill usage.
- Users can manually promote/demote skills.

Usage::

    from agent.curator import Curator

    curator = Curator(skills_dir="~/.Zeloo/skills")
    curator.track_usage("python-testing")
    curator.run_cycle()  # evaluate staleness, archive if needed
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SkillState(StrEnum):
    """Lifecycle states for a skill."""

    ACTIVE = "active"
    STALE = "stale"
    ARCHIVED = "archived"


@dataclass
class SkillRecord:
    """Metadata about a skill's lifecycle state."""

    name: str
    state: SkillState = SkillState.ACTIVE
    created_at: float = field(default_factory=time.time)
    last_used: float = 0.0
    use_count: int = 0
    last_evaluated: float = 0.0
    archived_at: float | None = None

    def mark_used(self) -> None:
        """Record that the skill was used."""
        self.last_used = time.time()
        self.use_count += 1
        # Using a skill reactivates it from stale/archived
        if self.state != SkillState.ACTIVE:
            self.state = SkillState.ACTIVE
            self.archived_at = None

    def days_since_last_use(self) -> float:
        """Return days since the skill was last used."""
        if self.last_used == 0:
            return (time.time() - self.created_at) / 86400
        return (time.time() - self.last_used) / 86400


class Curator:
    """Manages skill lifecycle: active → stale → archived.

    The curator tracks skill usage and periodically evaluates whether
    skills should be marked stale or archived based on inactivity.

    Args:
        skills_dir: Root directory containing skill folders.
        stale_after_days: Days of inactivity before a skill becomes stale.
        archive_after_days: Days of staleness before archiving.
        state_file: Path to the curator state JSON file.
    """

    def __init__(
        self,
        skills_dir: str | Path,
        stale_after_days: int = 30,
        archive_after_days: int = 90,
        state_file: str | Path | None = None,
    ) -> None:
        self._skills_dir = Path(skills_dir).expanduser()
        self._stale_after_days = stale_after_days
        self._archive_after_days = archive_after_days
        self._state_file = (
            Path(state_file).expanduser()
            if state_file
            else self._skills_dir / ".curator_state.json"
        )
        self._records: dict[str, SkillRecord] = {}
        self._load_state()

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------
    def _load_state(self) -> None:
        """Load curator state from disk."""
        if not self._state_file.exists():
            return
        try:
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
            for name, rec in data.items():
                self._records[name] = SkillRecord(
                    name=name,
                    state=SkillState(rec.get("state", "active")),
                    created_at=rec.get("created_at", time.time()),
                    last_used=rec.get("last_used", 0.0),
                    use_count=rec.get("use_count", 0),
                    last_evaluated=rec.get("last_evaluated", 0.0),
                    archived_at=rec.get("archived_at"),
                )
        except Exception:
            logger.exception("Failed to load curator state from %s", self._state_file)

    def _save_state(self) -> None:
        """Persist curator state to disk."""
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            data: dict[str, dict[str, Any]] = {}
            for name, rec in self._records.items():
                data[name] = {
                    "state": rec.state.value,
                    "created_at": rec.created_at,
                    "last_used": rec.last_used,
                    "use_count": rec.use_count,
                    "last_evaluated": rec.last_evaluated,
                    "archived_at": rec.archived_at,
                }
            self._state_file.write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )
        except Exception:
            logger.exception("Failed to save curator state to %s", self._state_file)

    # ------------------------------------------------------------------
    # Usage tracking
    # ------------------------------------------------------------------
    def track_usage(self, skill_name: str) -> None:
        """Record that a skill was used. Reactivates if stale/archived."""
        if skill_name not in self._records:
            self._records[skill_name] = SkillRecord(name=skill_name)
        rec = self._records[skill_name]
        rec.mark_used()
        self._save_state()
        logger.info(
            "Skill '%s' usage tracked (count=%d)", skill_name, rec.use_count
        )

    # ------------------------------------------------------------------
    # Lifecycle evaluation
    # ------------------------------------------------------------------
    def run_cycle(self) -> dict[str, int]:
        """Evaluate all skills and transition states based on inactivity.

        Returns a summary dict with counts of state transitions.
        """
        now = time.time()
        summary = {"stale": 0, "archived": 0, "active": 0}

        for name, rec in self._records.items():
            rec.last_evaluated = now
            days = rec.days_since_last_use()

            if rec.state == SkillState.ACTIVE and days >= self._stale_after_days:
                rec.state = SkillState.STALE
                summary["stale"] += 1
                logger.info("Skill '%s' marked stale (%.1f days unused)", name, days)
            elif rec.state == SkillState.STALE and days >= self._archive_after_days:
                rec.state = SkillState.ARCHIVED
                rec.archived_at = now
                summary["archived"] += 1
                logger.info("Skill '%s' archived (%.1f days stale)", name, days)

            if rec.state == SkillState.ACTIVE:
                summary["active"] += 1

        self._save_state()
        return summary

    # ------------------------------------------------------------------
    # Manual state management
    # ------------------------------------------------------------------
    def set_state(self, skill_name: str, state: SkillState) -> None:
        """Manually set a skill's state."""
        if skill_name not in self._records:
            self._records[skill_name] = SkillRecord(name=skill_name)
        rec = self._records[skill_name]
        rec.state = state
        if state == SkillState.ARCHIVED:
            rec.archived_at = time.time()
        elif state == SkillState.ACTIVE:
            rec.archived_at = None
        self._save_state()
        logger.info("Skill '%s' manually set to %s", skill_name, state.value)

    def get_state(self, skill_name: str) -> SkillState:
        """Get the current state of a skill."""
        if skill_name not in self._records:
            return SkillState.ACTIVE
        return self._records[skill_name].state

    def list_skills(self, state: SkillState | None = None) -> list[SkillRecord]:
        """List all skills, optionally filtered by state."""
        records = list(self._records.values())
        if state is not None:
            records = [r for r in records if r.state == state]
        return sorted(records, key=lambda r: r.name)

    def get_stats(self) -> dict[str, Any]:
        """Return curator statistics."""
        return {
            "total": len(self._records),
            "active": sum(1 for r in self._records.values() if r.state == SkillState.ACTIVE),
            "stale": sum(1 for r in self._records.values() if r.state == SkillState.STALE),
            "archived": sum(1 for r in self._records.values() if r.state == SkillState.ARCHIVED),
            "stale_after_days": self._stale_after_days,
            "archive_after_days": self._archive_after_days,
        }
