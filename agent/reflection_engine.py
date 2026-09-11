"""Reflection engine — message-level self-critique."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

ReflectionStrategy = Literal["none", "cheap_local", "llm_judge"]
DEFAULT_STATS_PATH = Path.home() / ".Zeloo" / "cache" / "reflection_engine" / "stats.json"

_RED_FLAG_TOKENS = (
    "i don't know", "i'm not sure", "as an ai",
    "i cannot", "i'm unable", "i apologize",
)
_RED_FLAG_TOOLS = {"unknown_tool", "delete_database", "drop_table"}
_LOW_CONFIDENCE_TOOL_PATTERNS = ("guess", "maybe", "try")


@dataclass
class ReflectionVerdict:
    """Outcome of a critique pass."""

    should_reroll: bool
    confidence: float
    reasons: list[str] = field(default_factory=list)
    suggested_fix: str | None = None
    strategy: ReflectionStrategy = "none"
    critiqued_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "should_reroll": self.should_reroll, "confidence": round(self.confidence, 4),
            "reasons": list(self.reasons), "suggested_fix": self.suggested_fix,
            "strategy": self.strategy, "critiqued_at": self.critiqued_at,
        }


@dataclass
class _CritiqueRecord:
    verdict: ReflectionVerdict
    accepted: bool
    recorded_at: float


class ReflectionEngine:
    """Self-critique messages using a configurable strategy.

    Strategies:
      * ``none`` — short-circuits with a high-confidence pass verdict.
      * ``cheap_local`` — deterministic regex / heuristic check.
      * ``llm_judge`` — delegates to a model via an injected callable.
    """

    def __init__(
        self,
        strategy: ReflectionStrategy = "cheap_local",
        llm_judge: Any | None = None,
        reroll_threshold: float = 0.4,
        stats_path: Path | None = None,
    ) -> None:
        if strategy not in ("none", "cheap_local", "llm_judge"):
            raise ValueError(f"unknown strategy: {strategy}")
        self.strategy = strategy
        self.llm_judge = llm_judge
        self.reroll_threshold = reroll_threshold
        self.stats_path = Path(stats_path) if stats_path else DEFAULT_STATS_PATH
        self.stats_path.parent.mkdir(parents=True, exist_ok=True)
        self._records: deque[_CritiqueRecord] = deque(maxlen=500)
        self._load_stats()

    async def critique(
        self,
        messages: list[dict[str, Any]],
        tools_used: list[str] | None = None,
    ) -> ReflectionVerdict:
        """Run critique on the most recent assistant message."""
        if self.strategy == "none":
            return ReflectionVerdict(should_reroll=False, confidence=1.0,
                                     reasons=["reflection disabled"], strategy="none")
        assistant_msg = self._last_assistant(messages)
        if assistant_msg is None:
            return ReflectionVerdict(should_reroll=False, confidence=0.5,
                                     reasons=["no assistant message to critique"],
                                     strategy=self.strategy)
        content = self._stringify_content(assistant_msg.get("content"))
        tools = tools_used or []
        if self.strategy == "cheap_local":
            verdict = self._cheap_local_critique(content, tools)
        else:
            verdict = await self._llm_judge_critique(content, tools)
        verdict.strategy = self.strategy
        return verdict

    def record_decision(self, verdict: ReflectionVerdict, accepted: bool) -> None:
        """Record whether the user accepted the critiqued response."""
        self._records.append(_CritiqueRecord(verdict=verdict, accepted=accepted,
                                            recorded_at=time.time()))
        self._persist_stats()

    def get_critique_stats(self) -> dict[str, Any]:
        """Return aggregate statistics about past critiques."""
        if not self._records:
            return {"total": 0, "accepted": 0, "rejected": 0, "rerolls": 0,
                    "acceptance_rate": 0.0, "avg_confidence": 0.0}
        total = len(self._records)
        accepted = sum(1 for r in self._records if r.accepted)
        rerolls = sum(1 for r in self._records if r.verdict.should_reroll)
        avg_conf = sum(r.verdict.confidence for r in self._records) / total
        return {"total": total, "accepted": accepted, "rejected": total - accepted,
                "rerolls": rerolls, "acceptance_rate": round(accepted / total, 4),
                "avg_confidence": round(avg_conf, 4)}

    def _cheap_local_critique(self, content: str, tools_used: list[str]) -> ReflectionVerdict:
        reasons: list[str] = []
        confidence = 1.0
        lower = content.lower()
        for marker in _RED_FLAG_TOKENS:
            if marker in lower:
                reasons.append(f"contains hedge phrase: {marker!r}")
                confidence -= 0.25
        if not content.strip():
            reasons.append("response is empty")
            confidence -= 0.5
        elif len(content.strip()) < 20:
            reasons.append("response is suspiciously short")
            confidence -= 0.2
        for tool in tools_used:
            if tool in _RED_FLAG_TOOLS:
                reasons.append(f"high-risk tool invoked: {tool}")
                confidence -= 0.3
        if not tools_used and re.search(r"\b(" + "|".join(_LOW_CONFIDENCE_TOOL_PATTERNS) + r")\b", lower):
            reasons.append("hedging language without grounding tool calls")
            confidence -= 0.15
        confidence = max(0.0, min(1.0, confidence))
        should_reroll = confidence < self.reroll_threshold
        suggested_fix = "Re-derive answer with concrete evidence and avoid hedging language." \
            if should_reroll else None
        return ReflectionVerdict(should_reroll=should_reroll, confidence=confidence,
                                 reasons=reasons, suggested_fix=suggested_fix)

    async def _llm_judge_critique(self, content: str, tools_used: list[str]) -> ReflectionVerdict:
        if self.llm_judge is None:
            logger.warning("llm_judge strategy selected but no judge provided; falling back to cheap_local")
            return self._cheap_local_critique(content, tools_used)
        prompt = (
            "You are a strict reviewer. Score the assistant's last message on a 0-1 "
            "confidence scale for correctness and groundedness. Reply with a JSON object "
            "with keys: confidence (float), should_reroll (bool), reasons (list[str]), "
            "suggested_fix (str|null).\n\n"
            f"Tools used: {tools_used}\nMessage:\n{content}\n"
        )
        try:
            raw = await self._invoke_judge(prompt)
            payload = self._parse_json(raw)
            return ReflectionVerdict(
                should_reroll=bool(payload.get("should_reroll", False)),
                confidence=float(payload.get("confidence", 0.5)),
                reasons=list(payload.get("reasons", [])),
                suggested_fix=payload.get("suggested_fix"),
            )
        except Exception as exc:
            logger.warning("LLM judge failed (%s); degrading to cheap_local", exc)
            return self._cheap_local_critique(content, tools_used)

    async def _invoke_judge(self, prompt: str) -> str:
        """Invoke the injected LLM judge. Supports sync or async callables."""
        result = self.llm_judge(prompt)
        if asyncio.iscoroutine(result):
            return await result
        return result

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        if not raw:
            return {}
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            raw = match.group(0)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _last_assistant(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
        for msg in reversed(messages):
            if msg.get("role") == "assistant":
                return msg
        return None

    @staticmethod
    def _stringify_content(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict):
                    text = block.get("text")
                    if text:
                        parts.append(str(text))
                else:
                    parts.append(str(block))
            return "\n".join(parts)
        return "" if content is None else str(content)

    def _load_stats(self) -> None:
        if not self.stats_path.exists():
            return
        try:
            raw = json.loads(self.stats_path.read_text(encoding="utf-8"))
            for entry in raw:
                self._records.append(_CritiqueRecord(
                    verdict=ReflectionVerdict(**entry["verdict"]),
                    accepted=entry["accepted"],
                    recorded_at=entry["recorded_at"],
                ))
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning("Failed to load reflection stats: %s", exc)

    def _persist_stats(self) -> None:
        try:
            payload = [{"verdict": r.verdict.to_dict(), "accepted": r.accepted,
                        "recorded_at": r.recorded_at} for r in self._records]
            tmp = self.stats_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(self.stats_path)
        except OSError as exc:
            logger.warning("Failed to persist reflection stats: %s", exc)