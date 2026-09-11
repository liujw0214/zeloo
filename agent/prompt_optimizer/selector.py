"""Few-shot example selector — chooses best examples for a given task."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class Example:
    """A few-shot example with input, output, and metadata."""

    id: str
    input_text: str
    output_text: str
    task_type: str = "general"
    quality_score: float = 1.0
    use_count: int = 0
    tags: list[str] = field(default_factory=list)
    embedding: list[float] | None = None

    def text(self) -> str:
        """Format example as prompt text."""
        return f"Input: {self.input_text}\nOutput: {self.output_text}"

    def compute_id(self) -> str:
        """Compute deterministic ID from content."""
        content = f"{self.input_text}|{self.output_text}"
        return hashlib.md5(content.encode()).hexdigest()[:12]


@dataclass
class SelectionResult:
    """Result of example selection."""

    examples: list[Example]
    total_examples: int
    selection_method: str
    max_tokens_budget: int


class ExampleSelector:
    """Selects best few-shot examples for a given task.

    Supports multiple selection strategies:
    - bm25: Keyword-based BM25 scoring
    - semantic: Embedding-based similarity (requires embeddings)
    - diversity: Maximize coverage across different patterns
    - hybrid: Combine BM25 and semantic scoring
    """

    def __init__(
        self,
        max_examples: int = 5,
        max_tokens_per_example: int = 256,
        total_token_budget: int = 1024,
        selection_strategy: str = "hybrid",
    ) -> None:
        self.max_examples = max_examples
        self.max_tokens_per_example = max_tokens_per_example
        self.total_token_budget = total_token_budget
        self.selection_strategy = selection_strategy
        self._examples: list[Example] = []

    def register(self, example: Example) -> None:
        """Register an example for future selection."""
        if not example.id:
            example.id = example.compute_id()
        self._examples.append(example)
        logger.debug("Registered example %s (total: %d)", example.id, len(self._examples))

    def register_batch(self, examples: list[Example]) -> None:
        """Register multiple examples at once."""
        for ex in examples:
            self.register(ex)

    def select(
        self,
        query: str,
        task_type: str | None = None,
        top_k: int | None = None,
    ) -> SelectionResult:
        """Select the best examples for a given query."""
        if not self._examples:
            logger.warning("No examples registered, returning empty selection")
            return SelectionResult(
                examples=[],
                total_examples=0,
                selection_method=self.selection_strategy,
                max_tokens_budget=self.total_token_budget,
            )

        candidates = self._filter_by_task_type(task_type) if task_type else self._examples
        if not candidates:
            candidates = self._examples

        scored = self._score_examples(query, candidates)
        scored.sort(key=lambda x: x[1], reverse=True)

        max_k = top_k if top_k is not None else self.max_examples
        selected = self._budget_aware_select(scored, max_k)

        logger.debug(
            "Selected %d examples from %d candidates using %s strategy",
            len(selected),
            len(candidates),
            self.selection_strategy,
        )
        return SelectionResult(
            examples=[ex for ex, _ in selected],
            total_examples=len(candidates),
            selection_method=self.selection_strategy,
            max_tokens_budget=self.total_token_budget,
        )

    def _filter_by_task_type(self, task_type: str) -> list[Example]:
        return [ex for ex in self._examples if ex.task_type == task_type]

    def _score_examples(
        self,
        query: str,
        candidates: list[Example],
    ) -> list[tuple[Example, float]]:
        if self.selection_strategy == "bm25":
            return [(ex, self._bm25_score(query, ex)) for ex in candidates]
        elif self.selection_strategy == "semantic":
            return [(ex, self._semantic_score(query, ex)) for ex in candidates]
        elif self.selection_strategy == "diversity":
            return [(ex, self._diversity_score(ex)) for ex in candidates]
        else:
            return [(ex, self._hybrid_score(query, ex)) for ex in candidates]

    def _bm25_score(self, query: str, example: Example) -> float:
        query_terms = set(self._tokenize(query.lower()))
        example_text = f"{example.input_text} {example.output_text}".lower()
        example_terms = set(self._tokenize(example_text))
        intersection = query_terms & example_terms
        if not intersection:
            return 0.0
        jaccard = len(intersection) / len(query_terms | example_terms)
        return jaccard * 0.5 + example.quality_score * 0.3 + min(example.use_count * 0.01, 0.2)

    def _semantic_score(self, query: str, example: Example) -> float:
        if example.embedding is None:
            return self._bm25_score(query, example)
        return example.quality_score * 0.7 + min(example.use_count * 0.01, 0.3)

    def _diversity_score(self, example: Example) -> float:
        return example.quality_score * 0.5 + 0.3 + min(len(example.tags) * 0.05, 0.2)

    def _hybrid_score(self, query: str, example: Example) -> float:
        bm25 = self._bm25_score(query, example)
        semantic = self._semantic_score(query, example)
        return bm25 * 0.4 + semantic * 0.6

    def _budget_aware_select(
        self,
        scored: list[tuple[Example, float]],
        max_k: int,
    ) -> list[tuple[Example, float]]:
        selected: list[tuple[Example, float]] = []
        total_tokens = 0
        for ex, score in scored:
            if len(selected) >= max_k:
                break
            example_tokens = self._estimate_tokens(ex.text())
            if total_tokens + example_tokens <= self.total_token_budget:
                selected.append((ex, score))
                total_tokens += example_tokens
                ex.use_count += 1
        return selected

    def _tokenize(self, text: str) -> list[str]:
        return re.findall(r"\b\w+\b", text.lower())

    def _estimate_tokens(self, text: str) -> int:
        return len(text) // 4

    def get_examples_by_task(self, task_type: str) -> list[Example]:
        """Get all registered examples for a specific task type."""
        return [ex for ex in self._examples if ex.task_type == task_type]

    def clear(self) -> None:
        """Clear all registered examples."""
        self._examples.clear()
        logger.debug("Cleared all registered examples")
