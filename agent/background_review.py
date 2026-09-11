"""Background review — asynchronous trajectory analysis for self-evolution.

Runs in a daemon thread after a complex turn. Uses a (potentially cheaper)
model to analyze the trajectory and extract reusable skills + durable
memory facts. Failures are logged and never propagate to the main loop.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_REVIEW_MODEL = os.environ.get("zeloo_REVIEW_MODEL", "gpt-4o-mini")

REVIEW_SYSTEM_PROMPT = """You are a trajectory analyzer for a self-evolving AI agent.
Given a conversation turn's trajectory, extract:
1. Reusable skills (non-trivial workflows that may recur)
2. Durable user facts or preferences (memory)

Output ONLY valid JSON with this shape:
{
  "skills": [{"name": "kebab-case-name", "description": "...", "content": "## Title\\nSteps..."}],
  "memories": [{"target": "user"|"memory", "content": "..."}]
}
- Skill names must be lowercase kebab-case.
- Skill content must start with YAML frontmatter (---\\nname: ...\\ndescription: ...\\n---).
- Memories are declarative facts, not instructions.
- If nothing is worth extracting, return {"skills": [], "memories": []}.
"""


def _load_trajectory(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Load the trajectory for the turn from the session DB."""
    try:
        from zeloo_state import SessionDB

        agent_home = payload.get("agent_home") or ""
        db_path = Path(agent_home) / "state.db" if agent_home else None
        db = SessionDB(db_path=db_path)

        session_id = payload["session_id"]
        turn_id = payload["turn_id"]

        # Query trajectories table directly for this turn
        row = db._conn.execute(
            "SELECT data FROM trajectories WHERE session_id = ? AND turn_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (session_id, turn_id),
        ).fetchone()

        db.close()
        if row is None:
            logger.warning("No trajectory found for session %s turn %s", session_id, turn_id)
            return None
        return json.loads(row["data"])
    except Exception:
        logger.exception("Failed to load trajectory")
        return None


def _call_review_model(
    trajectory: dict[str, Any], payload: dict[str, Any]
) -> dict[str, Any]:
    """Call the review model and return parsed JSON analysis."""
    model = payload.get("review_model") or DEFAULT_REVIEW_MODEL
    base_url = payload.get("base_url")

    try:
        from openai import OpenAI

        kwargs: dict[str, Any] = {"api_key": _resolve_api_key(payload)}
        if base_url:
            kwargs["base_url"] = base_url
        client = OpenAI(**kwargs)

        user_content = _format_trajectory_for_review(trajectory)

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.2,
            max_tokens=1500,
        )

        content = response.choices[0].message.content or "{}"
        return _parse_review_json(content)
    except Exception:
        logger.exception("Review model call failed")
        return {"skills": [], "memories": []}


def _resolve_api_key(payload: dict[str, Any]) -> str:
    """Resolve the API key from payload or environment."""
    import os

    return payload.get("api_key") or os.environ.get("OPENAI_API_KEY", "")


def _format_trajectory_for_review(trajectory: dict[str, Any]) -> str:
    """Format a trajectory into a concise review prompt."""
    lines = [
        f"User: {trajectory.get('user_message', '')}",
        f"Tool calls ({trajectory.get('tool_call_count', 0)}):",
    ]
    for tc in trajectory.get("tool_calls", []):
        fn = tc.get("function", {}) if isinstance(tc, dict) else {}
        name = fn.get("name", "?") if isinstance(fn, dict) else "?"
        args = fn.get("arguments", "{}") if isinstance(fn, dict) else "{}"
        lines.append(f"  - {name}({args})")

    assistant = trajectory.get("assistant_response", "")
    if assistant:
        lines.append(f"\nFinal response: {assistant[:500]}")

    return "\n".join(lines)


def _parse_review_json(content: str) -> dict[str, Any]:
    """Extract JSON from the model response (handles markdown fences)."""
    # Strip ```json fences if present
    match = re.search(r"\{[\s\S]*\}", content)
    if not match:
        return {"skills": [], "memories": []}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        logger.warning("Failed to parse review JSON: %s", content[:200])
        return {"skills": [], "memories": []}


# ── Validation ──────────────────────────────────────────────────────

def _validate_skill(candidate: dict[str, Any]) -> bool:
    """Validate a skill candidate before saving.

    Delegates to :func:`agent.skill_utils.validate_skill_candidate` for the
    structural and security checks, plus a local kebab-case name check.
    """
    from agent.skill_utils import (
        contains_secrets,
        has_valid_frontmatter,
        skill_exists,
    )

    name = (candidate.get("name") or "").strip()
    content = (candidate.get("content") or "").strip()

    # 1. Name must be non-empty and kebab-case
    if not name or not re.match(r"^[a-z0-9][a-z0-9-]*$", name):
        return False

    # 2. Content must not be empty
    if not content:
        return False

    # 3. No obvious secrets (API keys, passwords, private keys)
    if contains_secrets(content):
        return False

    # 4. Content must have valid frontmatter with a name field
    if not has_valid_frontmatter(content):
        return False

    # 5. Name must not conflict with an existing skill
    if skill_exists(name):
        return False

    return True


def _skill_exists(name: str, skills_dir: Path) -> bool:
    """Check if a skill directory already exists."""
    return (skills_dir / name / "SKILL.md").is_file()


# ── Public entry point ──────────────────────────────────────────────

def run_background_review(payload: dict[str, Any]) -> None:
    """Entry point for the background review thread.

    Args:
        payload: dict with session_id, turn_id, agent_home, model, provider,
                 base_url, and optionally api_key/review_model.
    """
    logger.info(
        "Background review started for session %s turn %s",
        payload.get("session_id"),
        payload.get("turn_id"),
    )

    trajectory = _load_trajectory(payload)
    if trajectory is None:
        return

    analysis = _call_review_model(trajectory, payload)

    skills = analysis.get("skills", [])
    memories = analysis.get("memories", [])

    skills_dir = _get_skills_dir(payload)
    saved_skills = 0
    for candidate in skills:
        if not _validate_skill(candidate):
            logger.debug("Skill candidate rejected validation: %s", candidate.get("name"))
            continue
        name = candidate["name"]
        if _skill_exists(name, skills_dir):
            logger.debug("Skill already exists, skipping: %s", name)
            continue
        try:
            skill_dir = skills_dir / name
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(candidate["content"], encoding="utf-8")
            saved_skills += 1
            logger.info("Auto-created skill: %s", name)
        except Exception:
            logger.exception("Failed to save skill %s", name)

    saved_memories = 0
    for item in memories:
        target = item.get("target", "memory")
        content = (item.get("content") or "").strip()
        if not content:
            continue
        try:
            from agent.memory_manager import MemoryStore

            agent_home = payload.get("agent_home")
            home = Path(agent_home) if agent_home else None
            store = MemoryStore(home=home)
            store.append(target, content)
            saved_memories += 1
        except Exception:
            logger.exception("Failed to append memory")

    logger.info(
        "Background review complete: %d skills saved, %d memories appended",
        saved_skills,
        saved_memories,
    )


def _get_skills_dir(payload: dict[str, Any]) -> Path:
    """Resolve the skills directory for this agent."""
    agent_home = payload.get("agent_home")
    if agent_home:
        return Path(agent_home) / "skills"
    from agent.zeloo_constants import get_skills_dir

    return get_skills_dir()
