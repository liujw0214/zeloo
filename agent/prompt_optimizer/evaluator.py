"""Prompt evaluator — measures prompt effectiveness."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class EvaluationResult:
    """Result of a prompt evaluation."""

    task_success: bool
    token_efficiency: float
    response_quality: float
    latency_ms: float
    score: float = 0.0
    feedback: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.score == 0.0:
            self.score = self._compute_score()

    def _compute_score(self) -> float:
        success_weight = 0.4
        quality_weight = 0.35
        efficiency_weight = 0.25
        return (
            success_weight * float(self.task_success)
            + quality_weight * self.response_quality
            + efficiency_weight * min(self.token_efficiency, 1.0)
        )


@dataclass
class PromptMetrics:
    """Aggregated metrics for a prompt over multiple evaluations."""

    prompt_id: str
    total_runs: int = 0
    successful_runs: int = 0
    avg_token_efficiency: float = 0.0
    avg_response_quality: float = 0.0
    avg_latency_ms: float = 0.0
    avg_score: float = 0.0
    history: list[EvaluationResult] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        if self.total_runs == 0:
            return 0.0
        return self.successful_runs / self.total_runs


class PromptEvaluator:
    """Evaluates prompt effectiveness based on task outcomes."""

    def __init__(
        self,
        task_type: str = "general",
        quality_threshold: float = 0.7,
        efficiency_threshold: float = 0.5,
    ) -> None:
        self.task_type = task_type
        self.quality_threshold = quality_threshold
        self.efficiency_threshold = efficiency_threshold
        self._metrics: dict[str, PromptMetrics] = {}

    def evaluate(
        self,
        prompt: str,
        response: str,
        task_success: bool,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
        quality_score: float | None = None,
    ) -> EvaluationResult:
        """Evaluate a single prompt-response pair."""
        total_tokens = prompt_tokens + completion_tokens
        token_efficiency = (
            completion_tokens / total_tokens if total_tokens > 0 else 0.0
        )
        response_quality = quality_score if quality_score is not None else 0.5

        result = EvaluationResult(
            task_success=task_success,
            token_efficiency=token_efficiency,
            response_quality=response_quality,
            latency_ms=latency_ms,
            metadata={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            },
        )
        logger.debug(
            "Evaluated prompt: success=%s score=%.3f efficiency=%.3f",
            task_success,
            result.score,
            token_efficiency,
        )
        return result

    def record(
        self,
        prompt_id: str,
        result: EvaluationResult,
    ) -> None:
        """Record an evaluation result for a prompt."""
        if prompt_id not in self._metrics:
            self._metrics[prompt_id] = PromptMetrics(prompt_id=prompt_id)

        m = self._metrics[prompt_id]
        m.total_runs += 1
        if result.task_success:
            m.successful_runs += 1

        n = m.total_runs
        m.avg_token_efficiency = (
            (m.avg_token_efficiency * (n - 1) + result.token_efficiency) / n
        )
        m.avg_response_quality = (
            (m.avg_response_quality * (n - 1) + result.response_quality) / n
        )
        m.avg_latency_ms = (
            (m.avg_latency_ms * (n - 1) + result.latency_ms) / n
        )
        m.avg_score = (m.avg_score * (n - 1) + result.score) / n
        m.history.append(result)

    def get_metrics(self, prompt_id: str) -> PromptMetrics | None:
        """Get aggregated metrics for a prompt."""
        return self._metrics.get(prompt_id)

    def is_effective(self, prompt_id: str, min_runs: int = 3) -> bool:
        """Check if a prompt is effective based on recorded metrics."""
        m = self._metrics.get(prompt_id)
        if m is None or m.total_runs < min_runs:
            return False
        return m.avg_score >= (self.quality_threshold * 0.7 + self.efficiency_threshold * 0.3)
