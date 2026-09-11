"""Enhanced PromptOptimizer v2 — combines all optimization capabilities.

Combines:
- evaluator: effectiveness scoring
- selector: few-shot example selection
- cot_engine: chain-of-thought injection
- tuner: parameter auto-tuning
- ab_test: A/B test framework
- compressor: token-efficient compression (NEW)
- template_library: curated templates (NEW)
- meta_prompt: LLM-driven optimization (NEW)
- safety: injection detection (NEW)
- report: analytics reporting (NEW)
"""

from __future__ import annotations

import logging
from typing import Any

from agent.prompt_optimizer.ab_test import ABTestRunner
from agent.prompt_optimizer.compressor import CompressionResult, PromptCompressor
from agent.prompt_optimizer.cot_engine import CoTEngine, CoTStyle
from agent.prompt_optimizer.evaluator import PromptEvaluator
from agent.prompt_optimizer.meta_prompt import (
    MetaPromptEngine,
    MetaPromptResult,
)
from agent.prompt_optimizer.report import OptimizationReportGenerator
from agent.prompt_optimizer.safety import (
    PromptSafetyValidator,
    SafetyReport,
    ThreatLevel,
)
from agent.prompt_optimizer.selector import ExampleSelector
from agent.prompt_optimizer.template_library import (
    PromptTemplate,
    PromptTemplateLibrary,
    TemplateCategory,
)
from agent.prompt_optimizer.tuner import PromptTuner

logger = logging.getLogger(__name__)


class PromptOptimizerV2:
    """Enhanced unified prompt optimizer combining all capabilities.

    Usage::

        optimizer = PromptOptimizerV2()

        # Optimize with safety check
        result = optimizer.optimize_safe(
            task_description="debug Python code",
            current_prompt="Fix this bug",
        )

        if result["safe"]:
            print(result["optimized_prompt"])
        else:
            print("Rejected:", result["report"])
    """

    def __init__(
        self,
        llm_provider: Any | None = None,
        enable_safety: bool = True,
        enable_compression: bool = True,
        enable_meta_prompt: bool = False,
    ) -> None:
        self.llm_provider = llm_provider
        self.enable_safety = enable_safety
        self.enable_compression = enable_compression
        self.enable_meta_prompt = enable_meta_prompt

        self.evaluator = PromptEvaluator()
        self.selector = ExampleSelector()
        self.cot_engine = CoTEngine()
        self.tuner = PromptTuner()
        self.template_library = PromptTemplateLibrary()
        self.meta_engine = MetaPromptEngine(llm_provider)
        self.report_generator = OptimizationReportGenerator()
        self.safety_validator = PromptSafetyValidator() if enable_safety else None
        self.compressor = PromptCompressor() if enable_compression else None

        self._ab_tests: dict[str, ABTestRunner] = {}

    def optimize_safe(
        self,
        task_description: str,
        current_prompt: str,
        task_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Optimize with full safety validation and reporting."""
        result: dict[str, Any] = {
            "safe": True,
            "optimized_prompt": current_prompt,
            "techniques_applied": [],
            "report": None,
            "safety_report": None,
            "compression": None,
            "recommendations": [],
        }

        original_text = current_prompt

        if self.safety_validator is not None:
            safety_report = self.safety_validator.validate(current_prompt)
            result["safety_report"] = safety_report
            if not safety_report.is_safe:
                result["safe"] = False
                result["report"] = (
                    f"Prompt rejected: threat level {safety_report.threat_level}"
                )
                result["recommendations"].append(
                    "Sanitize prompt using safety_validator.sanitize()"
                )
                return result
            if safety_report.sanitized_prompt:
                current_prompt = safety_report.sanitized_prompt

        if self.enable_compression and self.compressor is not None:
            compression = self.compressor.compress(current_prompt)
            result["compression"] = compression
            result["techniques_applied"].extend(compression.techniques_applied)
            current_prompt = compression.compressed_text

        if self.enable_meta_prompt and self.llm_provider is not None:
            variants = self.meta_engine.generate_variants(
                prompt=current_prompt,
                task_context=str(task_context) if task_context else "",
            )
            if variants.variants:
                if variants.recommended_variant_id:
                    recommended = next(
                        (v for v in variants.variants
                         if v.variant_id == variants.recommended_variant_id),
                        None,
                    )
                    if recommended is not None:
                        current_prompt = recommended.refined_prompt
                        result["techniques_applied"].append(
                            f"meta_prompt:{recommended.technique}"
                        )
                result["meta_variants"] = variants

        selection = self.selector.select(
            query=task_description, top_k=3,
        )
        if selection.examples:
            examples_text = "\n\n".join(ex.text() for ex in selection.examples)
            current_prompt = f"{examples_text}\n\n---\n\n{current_prompt}"
            result["techniques_applied"].append(
                f"few_shot:{len(selection.examples)}_examples"
            )

        enhanced = self.cot_engine.inject(
            prompt=current_prompt,
            style=self._infer_style(task_description),
        )
        if enhanced != current_prompt:
            result["techniques_applied"].append("chain_of_thought")
            current_prompt = enhanced

        result["optimized_prompt"] = current_prompt

        recommendations = self.report_generator.generate_recommendations(
            original_tokens=len(original_text) // 4,
            compressed_tokens=len(current_prompt) // 4,
            safety_threat_level=(
                result["safety_report"].threat_level.value
                if result["safety_report"] is not None
                else ThreatLevel.NONE.value
            ),
            variant_count=3,
        )
        result["recommendations"].extend(recommendations)

        report = self.report_generator.create_report(
            original_prompt=original_text,
            optimized_prompt=current_prompt,
            techniques=result["techniques_applied"],
            metrics={
                "original_length": len(original_text),
                "optimized_length": len(current_prompt),
                "compression_ratio": (
                    len(current_prompt) / max(len(original_text), 1)
                ),
                "techniques_count": len(result["techniques_applied"]),
            },
            recommendations=result["recommendations"],
        )
        result["report"] = report

        return result

    def use_template(
        self,
        template_id: str,
        context: dict[str, Any],
    ) -> str:
        """Render a template from the library."""
        template = self.template_library.get(template_id)
        if template is None:
            raise ValueError(f"Template {template_id} not found")
        rendered = template.render(context)
        template.record_use(success=True)
        return rendered

    def search_templates(
        self,
        query: str = "",
        category: TemplateCategory | None = None,
        tags: list[str] | None = None,
    ) -> list[PromptTemplate]:
        return self.template_library.search(
            query=query, category=category, tags=tags,
        )

    def generate_variants(
        self,
        prompt: str,
        task_context: str = "",
        num_variants: int = 3,
    ) -> MetaPromptResult:
        return self.meta_engine.generate_variants(
            prompt=prompt,
            task_context=task_context,
            num_variants=num_variants,
        )

    def compress(self, text: str) -> CompressionResult:
        if self.compressor is None:
            raise RuntimeError("Compression disabled")
        return self.compressor.compress(text)

    def validate_safety(self, text: str) -> SafetyReport:
        if self.safety_validator is None:
            raise RuntimeError("Safety validation disabled")
        return self.safety_validator.validate(text)

    def _infer_style(self, task: str) -> CoTStyle:
        task_lower = task.lower()
        if any(kw in task_lower for kw in ["math", "calculate", "equation"]):
            return CoTStyle.MATH
        if any(kw in task_lower for kw in ["code", "function", "debug"]):
            return CoTStyle.CODE
        if any(kw in task_lower for kw in ["compare", "vs", "difference"]):
            return CoTStyle.CONTRASTIVE
        if any(kw in task_lower for kw in ["decide", "choose", "tree"]):
            return CoTStyle.TREE
        return CoTStyle.BASIC


__all__ = ["PromptOptimizerV2"]