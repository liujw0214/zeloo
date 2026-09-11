"""Prompt tuner — auto-tuning of generation parameters."""

from __future__ import annotations

import logging
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class TuningConfig:
    """Configuration for parameter tuning."""

    temperature_range: tuple[float, float] = (0.0, 1.0)
    top_p_range: tuple[float, float] = (0.5, 1.0)
    top_k_range: tuple[int, int] = (1, 100)
    max_tokens_range: tuple[int, int] = (256, 4096)
    seed: int | None = None

    def sample(self) -> dict[str, Any]:
        """Sample a random configuration."""
        cfg: dict[str, Any] = {
            "temperature": random.uniform(*self.temperature_range),
            "top_p": random.uniform(*self.top_p_range),
            "top_k": random.randint(*self.top_k_range),
            "max_tokens": random.randint(*self.max_tokens_range),
        }
        if self.seed is not None:
            cfg["seed"] = self.seed
        return cfg


@dataclass
class TuningTrial:
    """A single tuning trial result."""

    config: dict[str, Any]
    score: float
    latency_ms: float
    tokens_used: int
    success: bool
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TuningResult:
    """Result of a tuning session."""

    best_config: dict[str, Any]
    best_score: float
    total_trials: int
    improvement: float
    trials: list[TuningTrial]


class PromptTuner:
    """Automatic tuning of generation parameters.

    Uses random search to find optimal parameter combinations
    for a given task. Supports temperature, top_p, top_k, max_tokens.
    """

    def __init__(
        self,
        config: TuningConfig | None = None,
        max_trials: int = 10,
        min_improvement: float = 0.05,
    ) -> None:
        self.config = config or TuningConfig()
        self.max_trials = max_trials
        self.min_improvement = min_improvement
        self._trials: list[TuningTrial] = []
        self._baseline_score: float = 0.5

    def tune(
        self,
        evaluate_fn: Callable[[dict[str, Any]], float],
        baseline_config: dict[str, Any] | None = None,
    ) -> TuningResult:
        """Run tuning trials to find optimal parameters.

        Args:
            evaluate_fn: Function that takes a config and returns a score (0-1).
            baseline_config: Optional baseline config to compare against.

        Returns:
            TuningResult with best configuration found.
        """
        if baseline_config:
            self._baseline_score = evaluate_fn(baseline_config)
            logger.info("Baseline score: %.3f", self._baseline_score)
        else:
            default_config = self.config.sample()
            self._baseline_score = evaluate_fn(default_config)
            logger.info("Initial baseline score: %.3f", self._baseline_score)

        self._trials.clear()
        best_score = self._baseline_score
        best_config = baseline_config or {}

        for i in range(self.max_trials):
            config = self.config.sample()
            try:
                score = evaluate_fn(config)
            except Exception as e:
                logger.warning("Trial %d failed: %s", i + 1, e)
                score = 0.0

            trial = TuningTrial(
                config=config,
                score=score,
                latency_ms=0.0,
                tokens_used=0,
                success=score > 0,
            )
            self._trials.append(trial)

            if score > best_score:
                best_score = score
                best_config = config
                logger.info("Trial %d: new best score %.3f", i + 1, score)

            if best_score >= self._baseline_score + self.min_improvement * 2:
                logger.info("Early stopping: sufficient improvement found")
                break

        improvement = best_score - self._baseline_score
        logger.info(
            "Tuning complete: best_score=%.3f improvement=%.3f from %d trials",
            best_score,
            improvement,
            len(self._trials),
        )
        return TuningResult(
            best_config=best_config,
            best_score=best_score,
            total_trials=len(self._trials),
            improvement=improvement,
            trials=self._trials,
        )

    def get_best_config(self) -> dict[str, Any] | None:
        """Get the best configuration from the last tuning run."""
        if not self._trials:
            return None
        best_trial = max(self._trials, key=lambda t: t.score)
        return best_trial.config

    def get_history(self) -> list[TuningTrial]:
        """Get the full trial history."""
        return list(self._trials)

    def suggest_configs(self, n: int = 3) -> list[dict[str, Any]]:
        """Suggest N diverse configurations for manual testing."""
        configs = []
        strategies = [
            {"temperature": 0.0, "top_p": 1.0, "top_k": 1},
            {"temperature": 0.7, "top_p": 0.9, "top_k": 40},
            {"temperature": 1.0, "top_p": 0.95, "top_k": 100},
        ]
        for s in strategies[:n]:
            cfg = self.config.sample()
            cfg.update(s)
            configs.append(cfg)
        return configs
