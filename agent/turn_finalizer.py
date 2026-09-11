"""Turn finalizer — post-turn self-evolution hooks.

Runs after each conversation turn completes. It does *not* block the
response from reaching the user; all heavy work (background review) is
dispatched asynchronously.

Responsibilities:
  * Decide whether to nudge the agent to write memory on the *next* turn.
  * Decide whether to nudge the agent to curate a skill on the *next* turn.
  * Persist the turn trajectory to the session DB for later review.
  * Optionally spawn a background review worker.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Thresholds for skill-worthiness heuristics
SKILL_WORTHY_MIN_TOOL_CALLS = 5
SKILL_WORTHY_MIN_DISTINCT_TOOLS = 3
MEMORY_NUDGE_KEYWORDS = (
    "i prefer",
    "i like",
    "i always",
    "i never",
    "my workflow",
    "remember that",
    "please note",
    "for future reference",
)


_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def _severity_rank_str(value: str) -> int:
    """Convert a severity name (``"high"`` / ``"HIGH"``) to its integer rank.

    Returns 0 for unknown values so callers can fall back to a default.
    """
    if not isinstance(value, str):
        return 0
    return _SEVERITY_RANK.get(value.strip().lower(), 0)


@dataclass
class TurnResult:
    """Summary of a single conversation turn for the finalizer."""

    session_id: str
    turn_id: int
    user_message: str
    assistant_response: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    success: bool = True
    error: str | None = None

    @property
    def tool_call_count(self) -> int:
        return len(self.tool_calls)

    @property
    def distinct_tool_names(self) -> set[str]:
        names: set[str] = set()
        for tc in self.tool_calls:
            fn = tc.get("function", {})
            name = fn.get("name") if isinstance(fn, dict) else None
            if name:
                names.add(name)
        return names


class TurnFinalizer:
    """Executes self-evolution hooks after each turn."""

    def __init__(
        self,
        background_review_enabled: bool = False,
        secret_alert_min_severity: str = "high",
        secret_scan_enabled: bool = True,
    ) -> None:
        self._background_review_enabled = background_review_enabled
        self._review_thread: threading.Thread | None = None
        self._secret_alert_min_severity = secret_alert_min_severity
        self._secret_scan_enabled = secret_scan_enabled
        self._secret_alert_count = 0  # process-wide counter (diagnostic)

    def finalize(self, agent: Any, turn_result: TurnResult) -> None:
        """Run all post-turn hooks. Never raises."""
        try:
            self._scan_assistant_output(agent, turn_result)
            self._evaluate_memory_nudge(agent, turn_result)
            self._evaluate_skill_nudge(agent, turn_result)
            self._record_trajectory(agent, turn_result)

            if self._background_review_enabled and self._should_review(turn_result):
                self._spawn_background_review(agent, turn_result)
        except Exception:
            logger.exception("TurnFinalizer.finalize failed")

    # ── Secret scanning (LLM output) ─────────────────────────────────

    def _scan_assistant_output(self, agent: Any, turn_result: TurnResult) -> None:
        """Scan the assistant's response for leaked credentials.

        Triage:
          * At or above ``alert_min_severity`` (default HIGH) → log
            warning, write ``llm_output_secret_alert`` audit event, and
            set ``agent._secret_alert`` so the next turn's volatile
            prompt can warn the model.
          * Strictly below the threshold → log info and write a
            ``llm_output_secret_flagged`` audit event (no nudge).

        Never raises — a scanner crash must not abort finalization.
        """
        if not self._secret_scan_enabled:
            return
        text = turn_result.assistant_response or ""
        if not text:
            return

        try:
            from agent.secret_scanner import (
                SecretScanner,
                SecretSeverity,
                severity_rank,
            )
        except Exception:  # noqa: BLE001
            return

        threshold_rank = _severity_rank_str(self._secret_alert_min_severity)
        if threshold_rank == 0:
            try:
                threshold_rank = severity_rank(SecretSeverity.HIGH)
            except Exception:  # noqa: BLE001
                threshold_rank = 3

        try:
            result = SecretScanner().scan(text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("turn_finalizer: secret scan failed: %s", exc)
            return

        if not result.has_findings:
            return

        max_rank = max(
            (
                severity_rank(f.severity)
                for f in result.findings
            ),
            default=0,
        )
        above_threshold = max_rank >= threshold_rank

        # Audit (always — flagged-only or alert).
        try:
            from agent.audit_log import audit_event

            event_kind = (
                "llm_output_secret_alert"
                if above_threshold
                else "llm_output_secret_flagged"
            )
            audit_event(
                event_kind,
                actor="agent",
                resource=f"session:{turn_result.session_id}:turn:{turn_result.turn_id}",
                outcome="ok",
                detail={
                    "counts_by_severity": result.by_severity,
                    "categories": sorted(result.categories),
                    "max_severity": (
                        result.findings[0].severity.value if result.findings else None
                    ),
                    "finding_count": len(result.findings),
                    "threshold": self._secret_alert_min_severity,
                },
            )
        except Exception:  # noqa: BLE001
            pass

        if above_threshold:
            self._secret_alert_count += 1
            summary = ", ".join(
                f"{cat}({n})"
                for cat, n in sorted(result.by_severity.items())
                if n > 0
            )
            logger.warning(
                "turn_finalizer: %d secret(s) in assistant output for session %s "
                "turn %d — [%s]",
                len(result.findings),
                turn_result.session_id,
                turn_result.turn_id,
                summary,
            )
            # Surface to the agent so the next-turn prompt can react.
            try:
                agent._secret_alert = {
                    "session_id": turn_result.session_id,
                    "turn_id": turn_result.turn_id,
                    "count": len(result.findings),
                    "categories": sorted(result.categories),
                    "summary": summary,
                }
            except Exception:  # noqa: BLE001
                pass
        else:
            logger.info(
                "turn_finalizer: %d low/medium secret(s) flagged (below alert threshold) "
                "for session %s turn %d",
                len(result.findings),
                turn_result.session_id,
                turn_result.turn_id,
            )

    # ── Memory nudge ────────────────────────────────────────────────

    def _evaluate_memory_nudge(self, agent: Any, turn_result: TurnResult) -> None:
        """Set agent._memory_nudge if this turn looks memory-worthy."""
        if not self._should_nudge_memory(turn_result):
            return
        logger.debug("Memory nudge armed for session %s", turn_result.session_id)
        agent._memory_nudge = True

    @staticmethod
    def _should_nudge_memory(turn_result: TurnResult) -> bool:
        """Heuristic: user expressed a preference or durable fact."""
        text = (turn_result.user_message or "").lower()
        return any(kw in text for kw in MEMORY_NUDGE_KEYWORDS)

    # ── Skill nudge ─────────────────────────────────────────────────

    def _evaluate_skill_nudge(self, agent: Any, turn_result: TurnResult) -> None:
        """Set agent._skill_nudge if this turn looks skill-worthy."""
        if not self._is_skill_worthy(turn_result):
            return
        logger.debug("Skill nudge armed for session %s", turn_result.session_id)
        agent._skill_nudge = True

    @staticmethod
    def _is_skill_worthy(turn_result: TurnResult) -> bool:
        """Heuristic: complex workflow that may be reusable."""
        if turn_result.tool_call_count < SKILL_WORTHY_MIN_TOOL_CALLS:
            return False
        if len(turn_result.distinct_tool_names) < SKILL_WORTHY_MIN_DISTINCT_TOOLS:
            return False
        return True

    # ── Trajectory recording ────────────────────────────────────────

    def _record_trajectory(self, agent: Any, turn_result: TurnResult) -> None:
        """Persist the turn trajectory to the session DB.

        Single-turn trajectories are truncated to a bounded size before
        storage to prevent a single verbose turn from bloating the DB.
        Multi-turn compression (head/tail + middle summary) is handled by
        :mod:`datagen.compress_trajectories` during background review / export.
        """
        from datagen.compress_trajectories import _truncate_turn

        session_db = getattr(agent, "_session_db", None)
        if session_db is None:
            return

        trajectory = {
            "session_id": turn_result.session_id,
            "turn_id": turn_result.turn_id,
            "user_message": turn_result.user_message,
            "assistant_response": turn_result.assistant_response,
            "tool_calls": turn_result.tool_calls,
            "tool_results": turn_result.tool_results,
            "tool_call_count": turn_result.tool_call_count,
            "distinct_tools": sorted(turn_result.distinct_tool_names),
            "success": turn_result.success,
            "error": turn_result.error,
        }
        trajectory = _truncate_turn(trajectory, max_chars=4000)

        try:
            session_db.save_trajectory(
                turn_result.session_id, turn_result.turn_id, trajectory
            )
        except Exception:
            logger.exception("Failed to save trajectory for turn %s", turn_result.turn_id)

    # ── Background review ───────────────────────────────────────────

    @staticmethod
    def _should_review(turn_result: TurnResult) -> bool:
        """Only review turns that produced a complex, successful workflow."""
        return turn_result.success and turn_result.tool_call_count >= SKILL_WORTHY_MIN_TOOL_CALLS

    def _spawn_background_review(self, agent: Any, turn_result: TurnResult) -> None:
        """Dispatch background review in a daemon thread.

        Imports lazily to avoid a circular dependency (background_review
        imports skill utilities which may import the agent package).
        """
        try:
            from agent.background_review import run_background_review

            # Pass only serializable data; the worker loads the agent fresh.
            payload = {
                "session_id": turn_result.session_id,
                "turn_id": turn_result.turn_id,
                "agent_home": getattr(agent, "_agent_home_path", None)
                or str(getattr(getattr(agent, "_session_db", None), "db_path", "").parent),
                "model": getattr(agent, "model", None),
                "provider": getattr(agent, "provider", None),
                "base_url": getattr(agent, "base_url", None),
            }

            self._review_thread = threading.Thread(
                target=run_background_review,
                args=(payload,),
                daemon=True,
                name=f"bg-review-{turn_result.session_id}-{turn_result.turn_id}",
            )
            self._review_thread.start()
            logger.info(
                "Background review dispatched for session %s turn %s",
                turn_result.session_id,
                turn_result.turn_id,
            )
        except Exception:
            logger.exception("Failed to spawn background review")


def build_nudge_prompt(agent: Any) -> str:
    """Build the volatile-tier nudge block for the next turn.

    Returns an empty string when no nudge is armed. Consumes the nudge
    flags so they only fire once.
    """
    parts: list[str] = []

    if getattr(agent, "_memory_nudge", False):
        agent._memory_nudge = False
        parts.append(
            "## Memory Nudge\n"
            "The previous turn may have revealed durable user preferences. "
            "If so, call the `memory` tool with action='append' to record them. "
            "Only write declarative facts, not instructions to yourself."
        )

    if getattr(agent, "_skill_nudge", False):
        agent._skill_nudge = False
        parts.append(
            "## Skill Nudge\n"
            "The previous turn solved a non-trivial workflow. If it is "
            "reusable, call `skill_manage` with action='create' to save it. "
            "Include YAML frontmatter (name, description) and a step-by-step body."
        )

    secret_alert = getattr(agent, "_secret_alert", None)
    if secret_alert:
        # Consume so the alert only fires once.
        try:
            agent._secret_alert = None
        except Exception:  # noqa: BLE001
            pass
        parts.append(
            "## Secret Leak Warning\n"
            f"Your previous response (turn {secret_alert.get('turn_id', '?')}) "
            f"contained {secret_alert.get('count', 0)} credential(s) "
            f"[{secret_alert.get('summary', '')}]. Treat those tokens as "
            "compromised, recommend the user rotate them, and avoid echoing "
            "them verbatim in future responses. Do NOT store the values in "
            "memory or skills."
        )

    return "\n\n".join(parts)
