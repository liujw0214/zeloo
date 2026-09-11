"""A/B testing framework for prompt variants."""

from __future__ import annotations

import hashlib
import logging
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class PromptVariant:
    """A prompt variant for A/B testing."""

    id: str
    name: str
    prompt_template: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id:
            self.id = hashlib.md5(self.prompt_template.encode()).hexdigest()[:8]

    def render(self, context: dict[str, Any]) -> str:
        """Render the variant with context variables."""
        try:
            return self.prompt_template.format(**context)
        except KeyError as e:
            logger.warning("Missing context variable %s in variant %s", e, self.name)
            return self.prompt_template


@dataclass
class TestResult:
    """Result of an A/B test."""

    variant_id: str
    variant_name: str
    impressions: int = 0
    successes: int = 0
    avg_latency_ms: float = 0.0
    avg_quality: float = 0.0
    conversion_rate: float = 0.0

    def record(self, success: bool, latency_ms: float, quality: float) -> None:
        """Record a single test outcome."""
        self.impressions += 1
        if success:
            self.successes += 1
        n = self.impressions
        self.avg_latency_ms = (self.avg_latency_ms * (n - 1) + latency_ms) / n
        self.avg_quality = (self.avg_quality * (n - 1) + quality) / n
        self.conversion_rate = self.successes / n


@dataclass
class ABTestResult:
    """Complete A/B test results."""

    test_id: str
    start_time: float
    end_time: float = 0.0
    status: str = "running"
    winner: str | None = None
    confidence: float = 0.0
    results: dict[str, TestResult] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> float:
        return self.end_time - self.start_time


class ABTestRunner:
    """A/B testing framework for prompt variants.

    Supports random traffic splitting, statistical significance
    testing, and automatic winner selection.
    """

    def __init__(
        self,
        test_id: str | None = None,
        traffic_split: dict[str, float] | None = None,
        min_sample_size: int = 30,
        confidence_threshold: float = 0.95,
    ) -> None:
        self.test_id = test_id or uuid.uuid4().hex[:8]
        self.traffic_split = traffic_split or {}
        self.min_sample_size = min_sample_size
        self.confidence_threshold = confidence_threshold
        self._variants: dict[str, PromptVariant] = {}
        self._results: dict[str, TestResult] = {}
        self._start_time: float = 0.0
        self._running = False
        self._user_assignment: dict[str, str] = {}

    def add_variant(self, variant: PromptVariant) -> None:
        """Add a prompt variant to the test."""
        self._variants[variant.id] = variant
        self._results[variant.id] = TestResult(
            variant_id=variant.id,
            variant_name=variant.name,
        )
        logger.debug("Added variant %s to test %s", variant.name, self.test_id)

    def start(self) -> None:
        """Start the A/B test."""
        if not self._variants:
            raise ValueError("Cannot start test with no variants")
        if len(self._variants) < 2:
            raise ValueError("A/B test requires at least 2 variants")

        self._start_time = time.time()
        self._running = True
        logger.info("Started A/B test %s with %d variants", self.test_id, len(self._variants))

    def stop(self) -> None:
        """Stop the A/B test."""
        self._running = False
        logger.info("Stopped A/B test %s", self.test_id)

    def assign(self, user_id: str) -> PromptVariant:
        """Assign a user to a variant (sticky assignment)."""
        if user_id in self._user_assignment:
            variant_id = self._user_assignment[user_id]
            return self._variants[variant_id]

        if self.traffic_split:
            r = random.random()
            cumulative = 0.0
            for variant_id, weight in self.traffic_split.items():
                cumulative += weight
                if r < cumulative:
                    self._user_assignment[user_id] = variant_id
                    return self._variants[variant_id]
            variant_id = list(self._variants.keys())[-1]
        else:
            variant_id = random.choice(list(self._variants.keys()))

        self._user_assignment[user_id] = variant_id
        return self._variants[variant_id]

    def record_outcome(
        self,
        variant_id: str,
        success: bool,
        latency_ms: float,
        quality: float,
    ) -> None:
        """Record an outcome for a variant."""
        if variant_id not in self._results:
            logger.warning("Unknown variant_id %s, skipping", variant_id)
            return
        self._results[variant_id].record(success, latency_ms, quality)

    def get_interim_results(self) -> dict[str, TestResult]:
        """Get current results without stopping the test."""
        return dict(self._results)

    def compute_winner(self) -> ABTestResult:
        """Compute the winner with statistical significance."""
        if not self._start_time:
            self._start_time = time.time()

        result = ABTestResult(
            test_id=self.test_id,
            start_time=self._start_time,
            end_time=time.time(),
            status="completed",
            results=dict(self._results),
        )

        variant_scores: list[tuple[str, float]] = []
        for vid, res in self._results.items():
            score = res.conversion_rate * 0.5 + res.avg_quality * 0.3 + (1.0 / (1.0 + res.avg_latency_ms / 1000)) * 0.2  # noqa: E501
            variant_scores.append((vid, score))

        variant_scores.sort(key=lambda x: x[1], reverse=True)
        if len(variant_scores) >= 2:
            best_id, best_score = variant_scores[0]
            second_id, second_score = variant_scores[1]
            gap = best_score - second_score
            result.confidence = min(1.0, gap * 5)
            result.winner = best_id

            if result.confidence >= self.confidence_threshold:
                logger.info(
                    "A/B test %s: winner=%s (confidence=%.2f)",
                    self.test_id,
                    self._variants[best_id].name,
                    result.confidence,
                )
            else:
                logger.info(
                    "A/B test %s: no significant winner (confidence=%.2f < %.2f)",
                    self.test_id,
                    result.confidence,
                    self.confidence_threshold,
                )

        return result

    def get_variant(self, variant_id: str) -> PromptVariant | None:
        """Get a variant by ID."""
        return self._variants.get(variant_id)

    def list_variants(self) -> list[PromptVariant]:
        """List all variants in the test."""
        return list(self._variants.values())



