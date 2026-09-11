"""Prompt Optimizer — automatic prompt optimization system.

Core modules:
- evaluator: Prompt effectiveness evaluation (task success rate, token efficiency)
- selector: Few-shot example selection (BM25 / semantic similarity)
- cot_engine: Chain-of-Thought template engine
- tuner: Auto-tuning (temperature/top_p/max_tokens combinations)
- ab_test: A/B testing framework for prompt variants

Enhanced modules (v2):
- compressor: Token-efficient prompt compression
- template_library: Curated, versioned prompt templates
- meta_prompt: LLM-driven meta-prompting for variants
- safety: Prompt injection and unsafe content detection
- report: Optimization analytics and reporting
- optimizer_v2: Unified enhanced optimizer combining all capabilities

Usage::

    from agent.prompt_optimizer import PromptOptimizerV2, PromptTemplate

    optimizer = PromptOptimizerV2()

    # Optimize with safety + compression + meta-prompting
    result = optimizer.optimize_safe(
        task_description="debug Python code",
        current_prompt="Fix the bug in this function",
    )

    # Use curated template
    rendered = optimizer.use_template(
        "builtin.system.helpful",
        {"date": "2026-09-09", "user_profile": "developer"},
    )

    # Validate safety
    safety = optimizer.validate_safety(text)
"""

from __future__ import annotations

from agent.prompt_optimizer.ab_test import ABTestResult, ABTestRunner, PromptVariant
from agent.prompt_optimizer.compressor import CompressionResult, PromptCompressor
from agent.prompt_optimizer.cot_engine import CoTEngine, CoTStyle, CoTTemplate
from agent.prompt_optimizer.evaluator import EvaluationResult, PromptEvaluator, PromptMetrics
from agent.prompt_optimizer.meta_prompt import (
    MetaPromptEngine,
    MetaPromptResult,
    MetaPromptVariant,
)
from agent.prompt_optimizer.optimizer import PromptOptimizer
from agent.prompt_optimizer.optimizer_v2 import PromptOptimizerV2
from agent.prompt_optimizer.report import (
    OptimizationReport,
    OptimizationReportGenerator,
)
from agent.prompt_optimizer.safety import (
    PromptSafetyValidator,
    SafetyFinding,
    SafetyReport,
    ThreatLevel,
)
from agent.prompt_optimizer.selector import Example, ExampleSelector, SelectionResult
from agent.prompt_optimizer.template_library import (
    PromptTemplate,
    PromptTemplateLibrary,
    TemplateCategory,
)
from agent.prompt_optimizer.tuner import PromptTuner, TuningConfig, TuningResult, TuningTrial

__all__ = [
    "PromptOptimizer",
    "PromptOptimizerV2",
    "PromptEvaluator",
    "PromptMetrics",
    "EvaluationResult",
    "ExampleSelector",
    "Example",
    "SelectionResult",
    "CoTEngine",
    "CoTStyle",
    "CoTTemplate",
    "PromptTuner",
    "TuningConfig",
    "TuningResult",
    "TuningTrial",
    "ABTestRunner",
    "ABTestResult",
    "PromptVariant",
    "PromptCompressor",
    "CompressionResult",
    "PromptTemplate",
    "PromptTemplateLibrary",
    "TemplateCategory",
    "MetaPromptEngine",
    "MetaPromptResult",
    "MetaPromptVariant",
    "PromptSafetyValidator",
    "SafetyFinding",
    "SafetyReport",
    "ThreatLevel",
    "OptimizationReport",
    "OptimizationReportGenerator",
]