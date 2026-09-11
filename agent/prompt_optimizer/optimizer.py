"""Prompt Optimizer — main facade combining all optimization capabilities."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from agent.prompt_optimizer.ab_test import ABTestResult, ABTestRunner, PromptVariant
from agent.prompt_optimizer.cot_engine import CoTEngine, CoTStyle, CoTTemplate
from agent.prompt_optimizer.evaluator import EvaluationResult, PromptEvaluator
from agent.prompt_optimizer.selector import Example, ExampleSelector, SelectionResult
from agent.prompt_optimizer.tuner import PromptTuner, TuningResult

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class PromptOptimizer:
    """Unified prompt optimization facade.

    Combines:
    - evaluator: Measures prompt effectiveness
    - selector: Selects best few-shot examples
    - cot_engine: Injects Chain-of-Thought guidance
    - tuner: Auto-tunes generation parameters
    - ab_test: A/B tests prompt variants

    Usage::

        optimizer = PromptOptimizer(agent=my_agent)

        # Select examples
        examples = optimizer.select_examples("debug Python code")

        # Inject CoT
        enhanced = optimizer.inject_cot(prompt, style="code")

        # Optimize
        improved = optimizer.optimize(task_description="debug Python code")
    """

    def __init__(
        self,
        agent: Any | None = None,
        enable_cot: bool = True,
        enable_few_shot: bool = True,
        enable_tuning: bool = True,
        enable_ab_test: bool = False,
    ) -> None:
        self.agent = agent
        self.enable_cot = enable_cot
        self.enable_few_shot = enable_few_shot
        self.enable_tuning = enable_tuning
        self.enable_ab_test = enable_ab_test

        self.evaluator = PromptEvaluator()
        self.selector = ExampleSelector()
        self.cot_engine = CoTEngine()
        self.tuner = PromptTuner()
        self._ab_tests: dict[str, ABTestRunner] = {}

    def optimize(
        self,
        task_description: str,
        current_prompt: str,
        context: dict[str, Any] | None = None,
        task_type: str | None = None,
    ) -> str:
        """Optimize a prompt for a given task.

        Applies all enabled optimizations in sequence:
        1. Few-shot example injection
        2. Chain-of-Thought guidance
        3. Context-aware templating
        """
        optimized = current_prompt

        if self.enable_few_shot:
            selection = self.selector.select(
                query=task_description,
                task_type=task_type,
            )
            if selection.examples:
                examples_text = "\n\n".join(ex.text() for ex in selection.examples)
                optimized = f"{examples_text}\n\n---\n\n{optimized}"
                logger.debug("Injected %d few-shot examples", len(selection.examples))

        if self.enable_cot:
            optimized = self.cot_engine.inject(
                prompt=optimized,
                style=task_type if task_type else "basic",
            )
            logger.debug("Injected CoT guidance")

        if context:
            try:
                optimized = optimized.format(**context)
            except KeyError as e:
                logger.warning("Missing context variable %s, using original prompt", e)

        return optimized

    def select_examples(
        self,
        query: str,
        task_type: str | None = None,
        top_k: int | None = None,
    ) -> SelectionResult:
        """Select best few-shot examples for a query."""
        return self.selector.select(query=query, task_type=task_type, top_k=top_k)

    def register_example(self, example: Example) -> None:
        """Register a few-shot example."""
        self.selector.register(example)

    def register_examples(self, examples: list[Example]) -> None:
        """Register multiple few-shot examples."""
        self.selector.register_batch(examples)

    def inject_cot(
        self,
        prompt: str,
        style: CoTStyle | str = CoTStyle.BASIC,
        force: bool = False,
    ) -> str:
        """Inject Chain-of-Thought guidance into a prompt."""
        return self.cot_engine.inject(prompt, style=style, force=force)

    def format_cot_steps(
        self,
        steps: list[dict[str, str]],
        style: CoTStyle | str = CoTStyle.BASIC,
    ) -> str:
        """Format reasoning steps into a CoT prompt."""
        return self.cot_engine.format_steps(steps, style=style)

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
        """Evaluate a prompt-response pair."""
        return self.evaluator.evaluate(
            prompt=prompt,
            response=response,
            task_success=task_success,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            quality_score=quality_score,
        )

    def record_evaluation(
        self,
        prompt_id: str,
        result: EvaluationResult,
    ) -> None:
        """Record an evaluation for later analysis."""
        self.evaluator.record(prompt_id, result)

    def tune_parameters(
        self,
        evaluate_fn,
        baseline_config: dict[str, Any] | None = None,
    ) -> TuningResult:
        """Tune generation parameters using the given evaluation function."""
        return self.tuner.tune(evaluate_fn, baseline_config)

    def create_ab_test(
        self,
        test_id: str,
        variants: list[PromptVariant],
        traffic_split: dict[str, float] | None = None,
    ) -> ABTestRunner:
        """Create and register an A/B test."""
        runner = ABTestRunner(
            test_id=test_id,
            traffic_split=traffic_split,
        )
        for v in variants:
            runner.add_variant(v)
        runner.start()
        self._ab_tests[test_id] = runner
        logger.info("Created A/B test %s with %d variants", test_id, len(variants))
        return runner

    def get_ab_test(self, test_id: str) -> ABTestRunner | None:
        """Get an existing A/B test runner."""
        return self._ab_tests.get(test_id)

    def get_ab_test_result(self, test_id: str) -> ABTestResult | None:
        """Get results for an A/B test."""
        runner = self._ab_tests.get(test_id)
        if runner is None:
            return None
        return runner.compute_winner()

    def register_cot_template(self, template: CoTTemplate) -> None:
        """Register a custom Chain-of-Thought template."""
        self.cot_engine.register_template(template)

    def list_cot_styles(self) -> list[str]:
        """List available Chain-of-Thought styles."""
        return self.cot_engine.list_styles()
