"""System-prompt assembly for AIAgent.

The agent's system prompt is built once per session and reused across all
turns — only context compression triggers a rebuild. This keeps the
upstream prefix cache warm.

Three tiers are joined with ``\\n\\n``:
* ``stable``   — identity (SOUL.md or DEFAULT_AGENT_IDENTITY), tool
  guidance, environment hints, coding brief, platform hints.
* ``context``  — caller-supplied ``system_message`` plus context files
  (AGENTS.md / .cursorrules / etc.) discovered under TERMINAL_CWD,
  plus the session's coding-workspace snapshot.
* ``volatile`` — skills index, memory snapshot, USER.md profile,
  timestamp/session/model/provider line.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.prompt_builder import (
    DEFAULT_AGENT_IDENTITY,
    MEMORY_GUIDANCE,
    PARALLEL_TOOL_CALL_GUIDANCE,
    PLATFORM_HINTS,
    SKILLS_GUIDANCE,
    TASK_COMPLETION_GUIDANCE,
    build_context_files_prompt,
    build_environment_hints,
    build_skills_system_prompt,
    load_soul_md,
)
from agent.runtime_cwd import resolve_context_cwd

logger = logging.getLogger(__name__)


def _agent_home(agent: Any) -> Any | None:
    """Return the agent's own profile home, or None for ambient resolution."""
    try:
        from agent.zeloo_constants import get_zeloo_home_override

        override = get_zeloo_home_override()
        if override:
            from pathlib import Path

            return Path(override)
    except Exception:
        pass
    try:
        db_path = getattr(getattr(agent, "_session_db", None), "db_path", None)
        if db_path:
            from pathlib import Path

            return Path(db_path).parent
    except Exception:
        pass
    return None


def _join_tier(parts: list[str | None]) -> str:
    """Join non-empty parts; None/blank entries are dropped."""
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


def _identity_parts(agent: Any, ctx_len: int | None) -> tuple[list[str], bool]:
    """SOUL.md or default identity. Returns (parts, soul_loaded)."""
    wants_soul = getattr(agent, "load_soul_identity", True) or not getattr(
        agent, "skip_context_files", False
    )
    soul_content = load_soul_md(ctx_len, home_override=_agent_home(agent)) if wants_soul else None
    if soul_content:
        return ([soul_content], True)
    return ([DEFAULT_AGENT_IDENTITY], False)


def _guidance_parts(agent: Any) -> list[str]:
    """Universal + tool-aware guidance blocks."""
    parts: list[str] = []
    valid_tools = getattr(agent, "valid_tool_names", set())
    if valid_tools:
        parts += [
            text
            for flag, text in (
                ("_task_completion_guidance", TASK_COMPLETION_GUIDANCE),
                ("_parallel_tool_call_guidance", PARALLEL_TOOL_CALL_GUIDANCE),
            )
            if getattr(agent, flag, True)
        ]
    # Memory guidance
    if "memory" in valid_tools:
        parts.append(MEMORY_GUIDANCE)
    # Skills guidance
    if "skill_manage" in valid_tools:
        parts.append(SKILLS_GUIDANCE)
    return parts


def _skills_prompt(agent: Any) -> str:
    """Skills index for the volatile tier."""
    valid_tools = getattr(agent, "valid_tool_names", set())
    if not any(name in valid_tools for name in ("skills_list", "skill_view", "skill_manage")):
        return ""
    try:
        available_toolsets = getattr(agent, "available_toolsets", set())
        return build_skills_system_prompt(
            available_tools=valid_tools,
            available_toolsets=available_toolsets,
            platform=getattr(agent, "platform", "cli"),
            skills_dir_override=_agent_home(agent) / "skills" if _agent_home(agent) else None,
        )
    except Exception:
        logger.exception("Failed to build skills prompt")
        return ""


def _memory_parts(agent: Any) -> list[str]:
    """Built-in memory/USER.md blocks."""
    parts: list[str] = []
    memory_store = getattr(agent, "_memory_store", None)
    if memory_store:
        for enabled, kind in (
            (getattr(agent, "_memory_enabled", True), "memory"),
            (getattr(agent, "_user_profile_enabled", True), "user"),
        ):
            if enabled:
                block = memory_store.format_for_system_prompt(kind)
                if block:
                    # Scrub any leaked credentials before injection.
                    scrubbed = _scrub_text(block, source=f"memory:{kind}")
                    parts.append(scrubbed)
    return parts


def _timestamp_line(agent: Any) -> str:
    """Date-only timestamp line; byte-stable for the day."""
    now = datetime.now()
    session_id = getattr(agent, "session_id", "")
    start_date = None
    if isinstance(session_id, str):
        m = re.match(r"^(\d{8})_(\d{6})", session_id)
        if m:
            try:
                start_date = datetime.strptime(f"{m.group(1)}_{m.group(2)}", "%Y%m%d_%H%M%S")
            except ValueError:
                pass
    if start_date is None:
        start_date = now

    line = f"Conversation started: {start_date.strftime('%A, %B %d, %Y')}"
    if now.strftime("%Y%m%d") != start_date.strftime("%Y%m%d"):
        line += f"\nToday's date (as of last rebuild): {now.strftime('%A, %B %d, %Y')}"

    trailer = (
        ("Model", getattr(agent, "model", None)),
        ("Provider", getattr(agent, "provider", None)),
        ("Platform", getattr(agent, "platform", None)),
    )
    line += "".join(f"\n{label}: {value}" for label, value in trailer if value)
    return line


def _scrub_text(text: str, *, source: str) -> str:
    """Run *text* through the secret scanner; log + audit on findings.

    Used to sanitize volatile-tier blocks (memory, USER, recent history)
    before they're joined into the system prompt. The scanner is
    fail-open: any exception returns the original text unchanged.
    """
    if not text:
        return text
    try:
        from agent.secret_scanner import SecretScanner
    except Exception:  # noqa: BLE001
        return text
    try:
        result = SecretScanner().scan_and_redact(text)
    except Exception:  # noqa: BLE001
        return text
    if not result.has_findings:
        return text
    redacted = result.redacted_text
    if redacted is None or redacted == text:
        return text
    try:
        from agent.audit_log import audit_event

        audit_event(
            "system_prompt_secret_found",
            actor="agent:system_prompt",
            resource=source,
            outcome="ok",
            detail={
                "finding_count": len(result.findings),
                "counts_by_severity": result.by_severity,
                "categories": sorted(result.categories),
            },
        )
    except Exception:  # noqa: BLE001
        pass
    logger.warning(
        "system_prompt: %d secret(s) redacted from %s",
        len(result.findings),
        source,
    )
    return redacted


def _history_snapshot(agent: Any) -> str:
    """Render the last few conversation turns as a markdown block.

    Lets the model re-anchor on recent context after compression,
    while the secret scanner removes any leaked credentials before
    the block enters the prompt.
    """
    turns = getattr(agent, "_history_snapshot_turns", 2)
    if not turns or turns <= 0:
        return ""
    messages = getattr(agent, "messages", []) or []
    if not messages:
        return ""

    # Convert messages to a compact transcript and take the last
    # ``2 * turns`` messages (user + assistant per turn).
    rendered: list[str] = []
    for m in messages[-(2 * turns):]:
        role = str(m.get("role", "user"))
        content = m.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                str(p.get("text", "")) if isinstance(p, dict) else str(p)
                for p in content
            )
        if not isinstance(content, str):
            content = str(content)
        # Truncate very long messages to keep the snapshot compact.
        if len(content) > 1500:
            content = content[:1500] + "\n…[truncated]"
        rendered.append(f"- **{role}**: {content}")

    if not rendered:
        return ""

    raw = "## Recent Conversation\n" + "\n".join(rendered)
    return _scrub_text(raw, source="history_snapshot")


def _platform_hint(agent: Any) -> str:
    """Platform-specific hint for the context tier."""
    platform = (getattr(agent, "platform", "") or "").lower().strip()
    return PLATFORM_HINTS.get(platform, "")


def build_system_prompt_parts(
    agent: Any, system_message: str | None = None
) -> dict[str, str]:
    """Assemble the system prompt as three ordered cache tiers.

    Returns a dict with keys "stable", "context", "volatile".
    Never re-rendered mid-session (only after compression).
    """
    # ── Stable tier ────────────────────────────────────────────────
    stable_parts, soul_loaded = _identity_parts(agent, None)
    stable_parts.extend(_guidance_parts(agent))
    stable_parts.append(build_environment_hints())

    # ── Context tier (cwd-dependent) ───────────────────────────────
    context_parts: list[str] = []
    context_parts.append(_platform_hint(agent))
    if system_message is not None:
        context_parts.append(system_message)
    if not getattr(agent, "skip_context_files", False):
        context_parts.append(
            build_context_files_prompt(
                cwd=resolve_context_cwd(),
                skip_soul=soul_loaded,
                home_override=_agent_home(agent),
            )
        )

    # ── Volatile tier (most likely to change; kept last) ───────────
    volatile_parts: list[str] = [_skills_prompt(agent), *_memory_parts(agent)]
    # Nudge block (memory/skill curation hints from the previous turn)
    try:
        from agent.turn_finalizer import build_nudge_prompt

        nudge = build_nudge_prompt(agent)
        if nudge:
            volatile_parts.append(nudge)
    except Exception:
        logger.exception("Failed to build nudge prompt")
    # Recent-conversation snapshot, scrubbed for secrets.
    snapshot = _history_snapshot(agent)
    if snapshot:
        volatile_parts.append(snapshot)
    volatile_parts.append(_timestamp_line(agent))

    return {
        "stable": _join_tier(stable_parts),
        "context": _join_tier(context_parts),
        "volatile": _join_tier(volatile_parts),
    }


def build_system_prompt(agent: Any, system_message: str | None = None) -> str:
    """Assemble the full prompt; cached on agent._cached_system_prompt."""
    parts = build_system_prompt_parts(agent, system_message=system_message)
    agent._cached_system_prompt_static = parts["stable"]
    return "\n\n".join(p for p in (parts["stable"], parts["context"], parts["volatile"]) if p)


def invalidate_system_prompt(agent: Any) -> None:
    """Force a rebuild on the next turn (after compression)."""
    agent._cached_system_prompt = None
    agent._cached_system_prompt_static = None
    memory_store = getattr(agent, "_memory_store", None)
    if memory_store:
        memory_store.load_from_disk()


class SystemPromptBuilder:
    """High-level system prompt builder backed by build_system_prompt().

    Provides a clean interface for the AgentInit bootstrap pipeline.
    """

    def __init__(
        self,
        tools: list[Any] | None = None,
        workspace_path: Path | None = None,
    ) -> None:
        self.tools = tools or []
        self.workspace_path = workspace_path

    def build(self, agent: Any, system_message: str | None = None) -> str:
        """Build the full system prompt for an agent."""
        return build_system_prompt(agent, system_message=system_message)

    def invalidate(self, agent: Any) -> None:
        """Invalidate the cached prompt on an agent."""
        invalidate_system_prompt(agent)
