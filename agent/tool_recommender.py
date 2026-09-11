"""Tool recommender — suggest the best tool for a given task."""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class ToolScore:
    """Score and reasoning for a tool recommendation."""

    tool_name: str
    score: float
    reasons: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolRecommendation:
    """A recommendation for tool usage."""

    primary_tool: ToolScore
    alternatives: list[ToolScore] = field(default_factory=list)
    task_type: str = "general"
    confidence: float = 0.0


class ToolRecommender:
    """Recommend the best tool for a given task.

    Uses keyword matching, tool descriptions, and historical
    usage patterns to suggest optimal tool choices.
    """

    KEYWORD_MAPPINGS: dict[str, list[str]] = {
        "file_read": ["read", "view", "show", "open", "cat"],
        "file_write": ["write", "save", "create", "edit", "modify"],
        "shell": ["run", "execute", "command", "shell", "bash"],
        "web_search": ["search", "find", "google", "lookup", "query"],
        "web_fetch": ["fetch", "download", "url", "website", "page"],
        "code_exec": ["python", "javascript", "compute", "calculate", "script"],
        "delegate": ["delegate", "subtask", "subagent", "spawn"],
        "memory": ["remember", "recall", "memory", "note"],
        "kanban": ["kanban", "board", "task", "todo"],
        "skill": ["skill", "workflow", "procedure"],
        "browser": ["browser", "navigate", "click", "screenshot"],
        "voice": ["voice", "speak", "audio", "tts"],
    }

    TOOL_TASK_AFFINITY: dict[str, list[str]] = {
        "file_read": ["information_retrieval", "code_review"],
        "file_write": ["code_modification", "content_creation"],
        "shell": ["system_admin", "build", "deployment"],
        "web_search": ["research", "current_events"],
        "web_fetch": ["content_extraction"],
        "code_exec": ["computation", "data_analysis", "scripting"],
        "delegate": ["complex_tasks", "parallelism"],
        "memory": ["context_management"],
        "kanban": ["project_management"],
        "browser": ["web_automation", "ui_testing"],
    }

    def __init__(self, tools: dict[str, dict[str, Any]] | None = None) -> None:
        self.tools = tools or {}
        self._usage_history: Counter = Counter()

    def register_tool(
        self,
        name: str,
        description: str,
        keywords: list[str] | None = None,
        category: str = "general",
    ) -> None:
        """Register a tool for recommendation."""
        self.tools[name] = {
            "description": description,
            "keywords": keywords or [],
            "category": category,
        }

    def record_usage(self, tool_name: str) -> None:
        """Record tool usage for history-based recommendations."""
        self._usage_history[tool_name] += 1

    def recommend(
        self,
        task_description: str,
        top_k: int = 3,
    ) -> ToolRecommendation:
        """Recommend best tool for task."""
        scores: dict[str, float] = {}
        reasons: dict[str, list[str]] = {}
        task_lower = task_description.lower()
        words = set(task_lower.split())

        for tool_name, mapping in self.KEYWORD_MAPPINGS.items():
            keyword_hits = sum(1 for kw in mapping if kw in task_lower)
            if keyword_hits > 0:
                scores[tool_name] = scores.get(tool_name, 0) + keyword_hits * 2
                reasons.setdefault(tool_name, []).append(
                    f"keyword_match: {keyword_hits} keywords"
                )

        for tool_name in self.tools:
            tool_desc = self.tools[tool_name].get("description", "")
            desc_words = set(tool_desc.split())
            overlap = len(words & desc_words)
            if overlap > 0:
                scores[tool_name] = scores.get(tool_name, 0) + overlap * 0.5
                reasons.setdefault(tool_name, []).append(
                    f"description_overlap: {overlap} words"
                )

        for tool_name, count in self._usage_history.items():
            if count > 0:
                usage_bonus = min(1.0, count * 0.1)
                scores[tool_name] = scores.get(tool_name, 0) + usage_bonus
                reasons.setdefault(tool_name, []).append(
                    f"historical_usage: {count} times"
                )

        for tool_name, affinity in self.TOOL_TASK_AFFINITY.items():
            for keyword in affinity:
                if keyword in task_lower:
                    scores[tool_name] = scores.get(tool_name, 0) + 1.5
                    reasons.setdefault(tool_name, []).append(
                        f"task_affinity: {keyword}"
                    )

        if not scores:
            default_tool = "reasoning"
            return ToolRecommendation(
                primary_tool=ToolScore(
                    tool_name=default_tool,
                    score=0.3,
                    reasons=["no_specific_match"],
                ),
                confidence=0.3,
            )

        sorted_tools = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        primary_name, primary_score = sorted_tools[0]
        # Confidence is primary_score as a fraction of the *theoretical*
        # maximum — keyword hits (×2) + description overlap (×0.5) +
        # usage bonus (≤1) + task affinity (×1.5). Normalising against the
        # observed top (which always equals primary_score) yielded a fixed
        # 0.5 confidence for every primary recommendation.
        theoretical_max = _max_possible_score(task_lower)
        confidence = (
            min(1.0, primary_score / theoretical_max)
            if theoretical_max > 0
            else 0.0
        )

        primary = ToolScore(
            tool_name=primary_name,
            score=primary_score,
            reasons=reasons.get(primary_name, []),
        )
        alternatives = [
            ToolScore(
                tool_name=name,
                score=score,
                reasons=reasons.get(name, []),
            )
            for name, score in sorted_tools[1:top_k]
        ]

        task_type = self._infer_task_type(task_lower)

        return ToolRecommendation(
            primary_tool=primary,
            alternatives=alternatives,
            task_type=task_type,
            confidence=confidence,
        )

    def _infer_task_type(self, task_lower: str) -> str:
        if any(kw in task_lower for kw in ["read", "view", "show"]):
            return "information_retrieval"
        if any(kw in task_lower for kw in ["write", "edit", "create"]):
            return "code_modification"
        if any(kw in task_lower for kw in ["search", "find"]):
            return "research"
        if any(kw in task_lower for kw in ["calculate", "compute"]):
            return "computation"
        return "general"


def _max_possible_score(task_lower: str) -> float:
    """Upper bound on the score any single tool can earn for *task_lower*.

    Components:
    * keyword hits × 2 per tool
    * description-overlap bonus — bounded by total tool description word
      count (conservative estimate of unique overlap)
    * usage history bonus ≤ 1.0
    * task-affinity bonus × 1.5 per matching keyword

    Used to normalise ``primary_score`` into a 0..1 confidence value.
    """
    keyword_max = 0
    for mapping in ToolRecommender.KEYWORD_MAPPINGS.values():
        keyword_max = max(keyword_max, sum(1 for kw in mapping if kw in task_lower))

    affinity_max = 0
    for affinity_list in ToolRecommender.TOOL_TASK_AFFINITY.values():
        affinity_max = max(
            affinity_max,
            sum(1 for kw in affinity_list if kw in task_lower),
        )

    # Description overlap is bounded by len(task words); we don't know the
    # tool descriptions here so the conservative bound is just |task words|.
    description_overlap_max = len(task_lower.split())

    return (
        keyword_max * 2.0
        + description_overlap_max * 0.5
        + 1.0  # historical usage bonus upper bound
        + affinity_max * 1.5
    )


__all__ = [
    "ToolScore",
    "ToolRecommendation",
    "ToolRecommender",
]