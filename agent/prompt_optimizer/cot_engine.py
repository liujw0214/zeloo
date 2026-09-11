"""Chain-of-Thought template engine."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class CoTStyle(StrEnum):
    """Chain-of-Thought reasoning styles."""

    BASIC = "basic"
    DETAILED = "detailed"
    MATH = "math"
    CODE = "code"
    CONTRASTIVE = "contrastive"
    TREE = "tree"


@dataclass
class CoTTemplate:
    """A Chain-of-Thought template."""

    name: str
    style: CoTStyle
    prefix: str
    suffix: str = ""
    step_template: str = "Step {n}: {reasoning}\nTherefore: {conclusion}"
    example: str = ""
    max_steps: int = 5
    metadata: dict[str, Any] = field(default_factory=dict)

    def format(self, steps: list[dict[str, str]]) -> str:
        """Format steps into a CoT prompt."""
        parts = [self.prefix]
        for i, step in enumerate(steps[: self.max_steps], 1):
            step_text = self.step_template.format(
                n=i,
                reasoning=step.get("reasoning", ""),
                conclusion=step.get("conclusion", ""),
            )
            parts.append(step_text)
        if self.suffix:
            parts.append(self.suffix)
        return "\n".join(parts)


DEFAULT_TEMPLATES: dict[CoTStyle, CoTTemplate] = {
    CoTStyle.BASIC: CoTTemplate(
        name="basic",
        style=CoTStyle.BASIC,
        prefix="Let me think step by step.",
        suffix="Therefore, the answer is:",
        step_template="Step {n}: {reasoning}\n→ {conclusion}",
    ),
    CoTStyle.DETAILED: CoTTemplate(
        name="detailed",
        style=CoTStyle.DETAILED,
        prefix="Let's analyze this problem systematically.\n",
        suffix="\nBased on the above analysis:",
        step_template="## Step {n}\nReasoning: {reasoning}\nConclusion: {conclusion}\n",
        max_steps=7,
    ),
    CoTStyle.MATH: CoTTemplate(
        name="math",
        style=CoTStyle.MATH,
        prefix="Let me solve this step by step.\n",
        suffix="\nFinal Answer:",
        step_template="{n}. {reasoning}\n   ∴ {conclusion}",
    ),
    CoTStyle.CODE: CoTTemplate(
        name="code",
        style=CoTStyle.CODE,
        prefix="Let me trace through the logic:\n",
        suffix="\n--- Final Implementation ---",
        step_template="// Step {n}: {reasoning}\n{conclusion}",
        max_steps=6,
    ),
    CoTStyle.CONTRASTIVE: CoTTemplate(
        name="contrastive",
        style=CoTStyle.CONTRASTIVE,
        prefix="Let me consider multiple approaches:\n",
        suffix="\nBest approach:",
        step_template="Option {n}: {reasoning}\n→ {conclusion}",
        max_steps=4,
    ),
    CoTStyle.TREE: CoTTemplate(
        name="tree",
        style=CoTStyle.TREE,
        prefix="Exploring decision tree:\n",
        suffix="\nOptimal path:",
        step_template="{'  ' * (depth)}├─ Step {n}: {reasoning}\n{'  ' * (depth + 1)}└─ {conclusion}",  # noqa: E501
        max_steps=8,
    ),
}


class CoTEngine:
    """Chain-of-Thought template engine.

    Provides structured reasoning templates that can be injected
    into prompts to improve model reasoning quality.
    """

    def __init__(
        self,
        default_style: CoTStyle = CoTStyle.BASIC,
        auto_detect: bool = True,
    ) -> None:
        self.default_style = default_style
        self.auto_detect = auto_detect
        self._templates: dict[CoTStyle, CoTTemplate] = dict(DEFAULT_TEMPLATES)
        self._task_type_map: dict[str, CoTStyle] = {
            "math": CoTStyle.MATH,
            "calculation": CoTStyle.MATH,
            "code": CoTStyle.CODE,
            "programming": CoTStyle.CODE,
            "debug": CoTStyle.CODE,
            "analysis": CoTStyle.DETAILED,
            "compare": CoTStyle.CONTRASTIVE,
            "decision": CoTStyle.TREE,
        }

    def get_template(self, style: CoTStyle | str) -> CoTTemplate:
        """Get a CoT template by style."""
        if isinstance(style, str):
            try:
                style = CoTStyle(style.lower())
            except ValueError:
                logger.warning("Unknown CoT style %r, using basic", style)
                style = CoTStyle.BASIC
        return self._templates.get(style, DEFAULT_TEMPLATES[CoTStyle.BASIC])

    def register_template(self, template: CoTTemplate) -> None:
        """Register a custom CoT template."""
        self._templates[template.style] = template
        logger.debug("Registered CoT template: %s", template.name)

    def inject(
        self,
        prompt: str,
        style: CoTStyle | str | None = None,
        force: bool = False,
    ) -> str:
        """Inject CoT guidance into a prompt."""
        if style is None:
            style = self._detect_style(prompt) if self.auto_detect else self.default_style

        template = self.get_template(style)

        if not force and self._has_cot_guidance(prompt):
            logger.debug("Prompt already contains CoT guidance, skipping injection")
            return prompt

        if "Let me think step by step" in prompt or "step by step" in prompt.lower():
            return prompt

        injected = f"{prompt.rstrip()}\n\n{template.prefix}"
        logger.debug("Injected CoT guidance (style=%s) into prompt", template.style)
        return injected

    def format_steps(
        self,
        steps: list[dict[str, str]],
        style: CoTStyle | str | None = None,
    ) -> str:
        """Format reasoning steps using a template."""
        if style is None:
            style = self.default_style
        template = self.get_template(style)
        return template.format(steps)

    def _detect_style(self, prompt: str) -> CoTStyle:
        """Auto-detect the best CoT style for a prompt."""
        prompt_lower = prompt.lower()

        for keyword, style in self._task_type_map.items():
            if keyword in prompt_lower:
                logger.debug("Detected CoT style %s for keyword '%s'", style, keyword)
                return style

        if any(kw in prompt_lower for kw in ["calculate", "equation", "math", "sum", "multiply"]):
            return CoTStyle.MATH
        if any(kw in prompt_lower for kw in ["function", "code", "debug", "implement"]):
            return CoTStyle.CODE
        if any(kw in prompt_lower for kw in ["compare", "difference", "versus", " vs "]):
            return CoTStyle.CONTRASTIVE
        if any(kw in prompt_lower for kw in ["analyze", "examine", "evaluate"]):
            return CoTStyle.DETAILED

        return self.default_style

    def _has_cot_guidance(self, prompt: str) -> bool:
        """Check if prompt already contains CoT guidance."""
        patterns = [
            r"step\s+by\s+step",
            r"chain\s+of\s+thought",
            r"reasoning:\s*\n",
            r"Let me think",
        ]
        return any(re.search(p, prompt, re.IGNORECASE) for p in patterns)

    def list_styles(self) -> list[str]:
        """List all available CoT styles."""
        return [s.value for s in CoTStyle]
