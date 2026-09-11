"""Smart approval: ML-style risk scoring and approval recommendation.

Combines four signals to decide whether a command can be auto-approved
without bothering the human operator:

1. Command pattern matching (regex rules from :mod:`tools.approval_detection`).
2. User history — commands the same user previously approved can usually
   be auto-approved again. Denials also count, in the opposite direction.
3. Risk scoring — derived from the command's risk level, whether it
   touches the network, performs file operations, requires elevated
   exit codes, etc. Output is an integer in ``[0, 100]``.
4. Time-based rules — auto-deny outside configured business hours, even
   if all other signals say "OK".

Every decision is recorded via :meth:`record_decision` so it can be
replayed or audited. The engine is intentionally lightweight — no
external ML dependency, just stdlib + the existing detection rules.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------


DEFAULT_CONFIG: dict[str, Any] = {
    # Auto-approve if the same user approved the same command pattern >= N times
    "auto_approve_threshold": 3,
    # Auto-deny if the same user denied the same pattern >= N times
    "auto_deny_threshold": 2,
    # Below this risk score, we auto-approve regardless of history
    "risk_auto_approve_below": 25,
    # Above this risk score, we never auto-approve
    "risk_auto_approve_above": 85,
    # Business hours (24h clock, inclusive of start, exclusive of end).
    "business_hours_start": dtime(9, 0),
    "business_hours_end": dtime(18, 0),
    # Days of the week considered business days (0 = Monday)
    "business_days": [0, 1, 2, 3, 4],
    # If true, deny everything outside business hours
    "deny_outside_business_hours": True,
    # Path of the audit log (relative paths resolved against cwd)
    "audit_log_path": ".zeloo/approval_smart_audit.jsonl",
    # Maximum length of any stored command pattern
    "max_pattern_length": 256,
}


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ApprovalDecision:
    """Outcome of a smart-approval evaluation."""

    should_approve: bool
    reason: str
    risk_score: int
    matched_pattern: str | None = None
    confidence: float = 0.0
    auto: bool = False  # True if the decision was made without human input

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict representation."""
        return {
            "should_approve": self.should_approve,
            "reason": self.reason,
            "risk_score": self.risk_score,
            "matched_pattern": self.matched_pattern,
            "confidence": round(self.confidence, 3),
            "auto": self.auto,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_command(command: str, max_length: int) -> str:
    """Normalize a command for pattern-key use.

    - Trims whitespace
    - Lowercases
    - Replaces variable-looking substrings (``/foo/123`` → ``/foo/<n>``)
    - Truncates to ``max_length``
    """
    if not command:
        return ""
    text = command.strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\b\d+\b", "<n>", text)
    if len(text) > max_length:
        text = text[:max_length]
    return text


def _safe_load_audit(path: Path) -> list[dict[str, Any]]:
    """Load an audit log, returning ``[]`` on any error."""
    try:
        if not path.exists():
            return []
        out: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except (ValueError, json.JSONDecodeError):
                    continue
        return out
    except OSError as exc:
        logger.debug("Audit log load error: %s", exc)
        return []


def _safe_append_audit(path: Path, record: dict[str, Any]) -> None:
    """Append a single record to the audit log, swallowing OS errors."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning("Audit log append error: %s", exc)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class SmartApprovalEngine:
    """ML-style smart approval engine.

    Combines command pattern matching, user history, a risk score and
    time-of-day rules to decide whether a command can be auto-approved.

    The engine keeps in-memory state (``history``, ``denial_count`` and
    ``audit_log``). All mutations are also written to a JSONL audit file
    so decisions survive process restarts.

    Args:
        config: Optional configuration override. Missing keys fall back
            to :data:`DEFAULT_CONFIG`.
    """

    # Words in commands that strongly suggest network access.
    NETWORK_KEYWORDS: tuple[str, ...] = (
        "curl",
        "wget",
        "ssh",
        "scp",
        "rsync",
        "nc ",
        "ncat",
        "telnet",
        "fetch",
        "http",
        "https",
        "ftp",
    )

    # Words that strongly suggest destructive file operations.
    DESTRUCTIVE_KEYWORDS: tuple[str, ...] = (
        "rm ",
        "rm\t",
        "delete",
        "drop ",
        "truncate",
        "shred",
        "wipefs",
    )

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        merged: dict[str, Any] = dict(DEFAULT_CONFIG)
        if config:
            for key, value in config.items():
                if value is not None:
                    merged[key] = value
        self.config: dict[str, Any] = merged

        # Pattern → approval count (and denials)
        self.history: dict[str, int] = {}
        self.denial_count: dict[str, int] = {}

        # Risk level weights (used by calculate_risk_score)
        self._risk_weights: dict[str, int] = {
            "safe": 0,
            "low": 15,
            "medium": 40,
            "high": 70,
            "critical": 95,
        }

        # Audit log entries kept in memory (mirrors on-disk file).
        self.audit_log: list[dict[str, Any]] = []

        # Lazy-loaded detection module (avoid import-time cycles)
        self._detection_module: Any | None = None

        # Pre-seed history from audit log on disk.
        self._load_audit_into_memory()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def learn(self, command: str, approved: bool) -> None:
        """Update the user-behaviour model.

        Args:
            command: The command the user just approved or denied.
            approved: ``True`` if the user approved, ``False`` if denied.
        """
        pattern = _normalize_command(command, self.config["max_pattern_length"])
        if not pattern:
            return

        if approved:
            self.history[pattern] = self.history.get(pattern, 0) + 1
            # A subsequent approval should *reduce* the accumulated denial
            # weight so a single accidental deny doesn't permanently taint
            # the user's behavior model.
            if self.denial_count.get(pattern):
                self.denial_count[pattern] = max(0, self.denial_count[pattern] - 1)
        else:
            self.denial_count[pattern] = self.denial_count.get(pattern, 0) + 1
            if self.history.get(pattern):
                self.history[pattern] = max(0, self.history[pattern] - 1)

        logger.debug(
            "Smart engine learned: pattern=%s approved=%s counts=%s/%s",
            pattern[:40],
            approved,
            self.history.get(pattern, 0),
            self.denial_count.get(pattern, 0),
        )

    def calculate_risk_score(
        self,
        command: str,
        context: dict[str, Any] | None = None,
    ) -> int:
        """Return a 0-100 risk score for ``command``.

        Scoring inputs (weighted):
        - Base score from ``approval_detection.get_command_risk_level``
        - +15 if the command contains network keywords
        - +20 if the command contains destructive keywords
        - +10 if ``context["elevated"]`` is True (sudo, runas, ...)
        - +10 if ``context["production"]`` is True
        - +5  if ``context["exit_code_target"]`` is high (>0)
        - -5  if ``context["dry_run"]`` is True (capped at 0)

        The result is clamped to ``[0, 100]``.

        Args:
            command: Command to score.
            context: Optional extra context that may amplify the score.

        Returns:
            Integer risk score in ``[0, 100]``.
        """
        if not command or not command.strip():
            return 0

        context = context or {}
        score = 0

        try:
            risk_level = self._get_risk_level(command)
            score += self._risk_weights.get(risk_level, 0)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Risk level lookup failed: %s", exc)
            score += 10  # default mild risk if detection is unavailable

        lowered = command.lower()
        if any(kw in lowered for kw in self.NETWORK_KEYWORDS):
            score += 15
        if any(kw in lowered for kw in self.DESTRUCTIVE_KEYWORDS):
            score += 20
        if context.get("elevated"):
            score += 10
        if context.get("production"):
            score += 10
        exit_target = context.get("exit_code_target")
        if isinstance(exit_target, int) and exit_target > 0:
            score += 5
        if context.get("dry_run"):
            score = max(0, score - 5)

        return max(0, min(100, score))

    def should_auto_approve(
        self,
        command: str,
        context: dict[str, Any] | None = None,
    ) -> tuple[bool, str]:
        """Determine whether ``command`` should be auto-approved.

        Returns a tuple ``(should_approve, reason)``. ``should_approve``
        is ``True`` only when the engine decided, based on the configured
        rules, that human input is not necessary.

        Args:
            command: Command under evaluation.
            context: Optional execution context (same shape as
                :meth:`calculate_risk_score`).
        """
        if not command or not command.strip():
            return True, "empty_command"

        # 1. Time-based rule: outside business hours → auto-deny.
        if (
            self.config.get("deny_outside_business_hours", True)
            and not self.is_business_hours()
        ):
            return False, "outside_business_hours"

        pattern = _normalize_command(command, self.config["max_pattern_length"])
        risk_score = self.calculate_risk_score(command, context)
        below_threshold = risk_score < self.config["risk_auto_approve_below"]
        above_threshold = risk_score > self.config["risk_auto_approve_above"]

        # 2. Hard upper bound — never auto-approve dangerous stuff.
        if above_threshold:
            return False, f"risk_too_high:{risk_score}"

        # 3. Pattern history: enough approvals → auto-approve.
        approvals = self.history.get(pattern, 0)
        denials = self.denial_count.get(pattern, 0)
        if (
            approvals >= self.config["auto_approve_threshold"]
            and denials < self.config["auto_deny_threshold"]
            and not above_threshold
        ):
            return True, f"history_match:{approvals}_approvals"

        # 4. Pattern history: many denials → auto-deny.
        if denials >= self.config["auto_deny_threshold"]:
            return False, f"history_denial:{denials}_denials"

        # 5. Risk-only fallback.
        if below_threshold:
            return True, f"low_risk:{risk_score}"

        return False, f"insufficient_signal:risk={risk_score},approvals={approvals}"

    def is_business_hours(self, now: datetime | None = None) -> bool:
        """Check whether ``now`` is inside the configured business window.

        If ``now`` is omitted, uses ``datetime.now()``. The check is
        inclusive of the start time, exclusive of the end time, and
        restricts to the configured ``business_days``.

        Args:
            now: Optional override for the current time (useful in tests).
        """
        moment = now or datetime.now()
        if moment.weekday() not in self.config.get("business_days", [0, 1, 2, 3, 4]):
            return False

        start: dtime = self.config["business_hours_start"]
        end: dtime = self.config["business_hours_end"]
        current = moment.time()
        if start <= end:
            return start <= current < end
        # Wrap-around window (e.g. 22:00 → 06:00 next day)
        return current >= start or current < end

    def record_decision(
        self,
        command: str,
        approved: bool,
        reason: str,
    ) -> dict[str, Any]:
        """Record an approval decision for audit.

        Updates ``self.learn``, appends a JSONL record to the audit file
        and stores the same record in memory.

        Args:
            command: The command that was decided on.
            approved: ``True`` for approval, ``False`` for denial.
            reason: Free-form reason (e.g. ``"user_approved"``).

        Returns:
            The persisted audit record (dict).
        """
        pattern = _normalize_command(command, self.config["max_pattern_length"])
        self.learn(command, approved)
        record = {
            "ts": time.time(),
            "command": command[: self.config["max_pattern_length"]],
            "pattern": pattern,
            "approved": bool(approved),
            "reason": reason,
        }
        self.audit_log.append(record)

        log_path_raw = self.config.get("audit_log_path", ".zeloo/approval_smart_audit.jsonl")
        log_path = Path(log_path_raw)
        if not log_path.is_absolute():
            log_path = Path.cwd() / log_path
        _safe_append_audit(log_path, record)
        return record

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def evaluate(
        self,
        command: str,
        context: dict[str, Any] | None = None,
    ) -> ApprovalDecision:
        """Evaluate ``command`` and return a structured decision.

        This is a thin convenience wrapper around
        :meth:`should_auto_approve` and :meth:`calculate_risk_score`
        that returns an :class:`ApprovalDecision` with a confidence value
        derived from the input signals.
        """
        should, reason = self.should_auto_approve(command, context)
        risk_score = self.calculate_risk_score(command, context)
        pattern = _normalize_command(command, self.config["max_pattern_length"])

        approvals = self.history.get(pattern, 0)
        denials = self.denial_count.get(pattern, 0)
        confidence = min(
            1.0,
            (approvals + 1) / (self.config["auto_approve_threshold"] + 1)
            + (denials == 0) * 0.1,
        )

        return ApprovalDecision(
            should_approve=should,
            reason=reason,
            risk_score=risk_score,
            matched_pattern=pattern or None,
            confidence=confidence,
            auto=True,
        )

    def stats(self) -> dict[str, Any]:
        """Return aggregate stats for diagnostics / health endpoints."""
        total_approvals = sum(self.history.values())
        total_denials = sum(self.denial_count.values())
        return {
            "patterns_known": len(self.history),
            "patterns_denied": len(self.denial_count),
            "total_approvals": total_approvals,
            "total_denials": total_denials,
            "audit_entries": len(self.audit_log),
            "config": {
                k: (str(v) if isinstance(v, dtime) else v)
                for k, v in self.config.items()
            },
        }

    def reset(self) -> None:
        """Clear in-memory history and the audit log.

        Does **not** delete the on-disk audit file — call
        :meth:`clear_audit_file` for that.
        """
        self.history.clear()
        self.denial_count.clear()
        self.audit_log.clear()

    def clear_audit_file(self) -> bool:
        """Delete the on-disk audit file. Returns ``True`` on success."""
        log_path = Path(self.config.get("audit_log_path", ".zeloo/approval_smart_audit.jsonl"))
        if not log_path.is_absolute():
            log_path = Path.cwd() / log_path
        try:
            if log_path.exists():
                log_path.unlink()
            return True
        except OSError as exc:
            logger.warning("Audit file delete failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_risk_level(self, command: str) -> str:
        """Look up the risk level via the detection module.

        The detection module is cached to avoid import cycles at
        construction time and to keep ``SmartApprovalEngine`` usable in
        unit tests where the module may not be available.
        """
        if self._detection_module is None:
            try:
                from tools import approval_detection as detection  # type: ignore
            except Exception as exc:  # pragma: no cover - very defensive
                logger.debug("approval_detection unavailable: %s", exc)
                detection = None
            self._detection_module = detection

        detection = self._detection_module
        if detection is None:
            return "low"
        try:
            return detection.get_command_risk_level(command)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("get_command_risk_level failed: %s", exc)
            return "low"

    def _load_audit_into_memory(self) -> None:
        """Re-seed ``history`` / ``denial_count`` from the audit file."""
        log_path = Path(self.config.get("audit_log_path", ".zeloo/approval_smart_audit.jsonl"))
        if not log_path.is_absolute():
            log_path = Path.cwd() / log_path

        records: Iterable[dict[str, Any]] = _safe_load_audit(log_path)
        for rec in records:
            pattern = rec.get("pattern") or ""
            if not pattern:
                continue
            approved = bool(rec.get("approved"))
            if approved:
                self.history[pattern] = self.history.get(pattern, 0) + 1
            else:
                self.denial_count[pattern] = self.denial_count.get(pattern, 0) + 1
            self.audit_log.append(rec)


__all__ = ["SmartApprovalEngine", "ApprovalDecision", "DEFAULT_CONFIG"]