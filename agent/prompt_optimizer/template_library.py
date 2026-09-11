"""Prompt template library — versioned, tagged, searchable."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class TemplateCategory(StrEnum):
    """Categories of prompt templates."""

    SYSTEM = "system"
    USER = "user"
    INSTRUCTION = "instruction"
    CHAIN_OF_THOUGHT = "chain_of_thought"
    FEW_SHOT = "few_shot"
    ROLE_PLAY = "role_play"
    EXTRACTION = "extraction"
    SUMMARIZATION = "summarization"
    CLASSIFICATION = "classification"
    GENERATION = "generation"
    REASONING = "reasoning"
    TRANSLATION = "translation"
    CODE = "code"


@dataclass
class PromptTemplate:
    """A versioned prompt template."""

    template_id: str
    name: str
    category: TemplateCategory
    template: str
    variables: list[str] = field(default_factory=list)
    description: str = ""
    version: str = "1.0.0"
    tags: list[str] = field(default_factory=list)
    author: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    usage_count: int = 0
    success_rate: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def render(self, context: dict[str, Any]) -> str:
        """Render template with variable substitution."""
        try:
            return self.template.format(**context)
        except KeyError as e:
            missing = e.args[0]
            return self.template.replace(
                "{" + missing + "}",
                f"[MISSING:{missing}]"
            )

    def record_use(self, success: bool = True) -> None:
        self.usage_count += 1
        if success:
            self.success_rate = (
                (self.success_rate * (self.usage_count - 1) + 1.0)
                / self.usage_count
            )
        else:
            self.success_rate = (
                (self.success_rate * (self.usage_count - 1))
                / self.usage_count
            )


class PromptTemplateLibrary:
    """Versioned library of prompt templates with search and stats."""

    BUILTIN_TEMPLATES: list[PromptTemplate] = [
        PromptTemplate(
            template_id="builtin.system.helpful",
            name="Helpful Assistant",
            category=TemplateCategory.SYSTEM,
            template=(
                "You are a helpful, harmless, and honest AI assistant. "
                "Always provide accurate information and acknowledge uncertainty. "
                "If you don't know something, say so clearly.\n\n"
                "Today's date: {date}\nUser profile: {user_profile}"
            ),
            variables=["date", "user_profile"],
            description="Standard helpful assistant system prompt",
            tags=["general", "system", "default"],
            author="system",
        ),
        PromptTemplate(
            template_id="builtin.cot.math",
            name="Math Chain-of-Thought",
            category=TemplateCategory.CHAIN_OF_THOUGHT,
            template=(
                "Solve the following problem step by step.\n\n"
                "Problem: {problem}\n\n"
                "Step 1: Identify the given information\n"
                "Step 2: Determine what needs to be found\n"
                "Step 3: Apply relevant formulas or methods\n"
                "Step 4: Calculate the answer\n"
                "Step 5: Verify the result\n\n"
                "Final Answer: {answer_format}"
            ),
            variables=["problem", "answer_format"],
            description="Mathematical problem solving with CoT",
            tags=["math", "reasoning", "chain-of-thought"],
            author="system",
        ),
        PromptTemplate(
            template_id="builtin.extraction.json",
            name="Structured JSON Extraction",
            category=TemplateCategory.EXTRACTION,
            template=(
                "Extract information from the following text into structured JSON.\n\n"
                "Text: {text}\n\n"
                "Output format:\n{schema}\n\n"
                "Provide ONLY valid JSON matching the schema. No commentary."
            ),
            variables=["text", "schema"],
            description="Extract structured data from text",
            tags=["extraction", "json", "structured"],
            author="system",
        ),
        PromptTemplate(
            template_id="builtin.code.review",
            name="Code Review",
            category=TemplateCategory.CODE,
            template=(
                "Review the following {language} code for:\n"
                "- Correctness\n- Performance\n- Security\n- Readability\n- Best practices\n\n"
                "Code:\n```{language}\n{code}\n```\n\n"
                "Provide feedback in this format:\n"
                "## Issues Found\n## Suggestions\n## Refactored Code"
            ),
            variables=["language", "code"],
            description="Comprehensive code review",
            tags=["code", "review", "programming"],
            author="system",
        ),
        PromptTemplate(
            template_id="builtin.summary.bullets",
            name="Bullet Summary",
            category=TemplateCategory.SUMMARIZATION,
            template=(
                "Summarize the following text in {num_bullets} bullet points.\n"
                "Each bullet should be concise (max 20 words).\n\n"
                "Text:\n{text}\n\n"
                "Bullets:"
            ),
            variables=["num_bullets", "text"],
            description="Concise bullet-point summary",
            tags=["summary", "bullets", "concise"],
            author="system",
        ),
        PromptTemplate(
            template_id="builtin.classify.sentiment",
            name="Sentiment Classification",
            category=TemplateCategory.CLASSIFICATION,
            template=(
                "Classify the sentiment of the following text.\n"
                "Possible labels: {labels}\n"
                "Output format: One of the labels, then a brief justification.\n\n"
                "Text: {text}\n\n"
                "Sentiment:"
            ),
            variables=["labels", "text"],
            description="Multi-class sentiment classification",
            tags=["classification", "sentiment", "nlp"],
            author="system",
        ),
        PromptTemplate(
            template_id="builtin.translate",
            name="Language Translation",
            category=TemplateCategory.TRANSLATION,
            template=(
                "Translate the following text from {source_lang} to {target_lang}.\n"
                "Preserve tone, style, and technical terminology.\n\n"
                "Text: {text}\n\n"
                "Translation:"
            ),
            variables=["source_lang", "target_lang", "text"],
            description="Multi-language translation",
            tags=["translation", "multilingual"],
            author="system",
        ),
        PromptTemplate(
            template_id="builtin.reasoning.decompose",
            name="Problem Decomposition",
            category=TemplateCategory.REASONING,
            template=(
                "Decompose the following complex problem into smaller sub-problems.\n"
                "Solve each sub-problem independently, then combine results.\n\n"
                "Problem: {problem}\n\n"
                "Provide:\n"
                "1. Sub-problem breakdown\n"
                "2. Solution to each sub-problem\n"
                "3. Combined final answer"
            ),
            variables=["problem"],
            description="Decompose-and-solve complex problems",
            tags=["reasoning", "decomposition", "complex"],
            author="system",
        ),
    ]

    def __init__(self) -> None:
        self._templates: dict[str, PromptTemplate] = {}
        for template in self.BUILTIN_TEMPLATES:
            self._templates[template.template_id] = template

    def add(self, template: PromptTemplate) -> None:
        """Add or update a template."""
        if template.template_id in self._templates:
            template.updated_at = time.time()
        self._templates[template.template_id] = template
        logger.debug("Added template %s (%s)", template.template_id, template.category)

    def get(self, template_id: str) -> PromptTemplate | None:
        return self._templates.get(template_id)

    def search(
        self,
        query: str = "",
        category: TemplateCategory | None = None,
        tags: list[str] | None = None,
        limit: int = 20,
    ) -> list[PromptTemplate]:
        results = list(self._templates.values())
        if category:
            results = [t for t in results if t.category == category]
        if tags:
            results = [
                t for t in results if any(tag in t.tags for tag in tags)
            ]
        if query:
            query_lower = query.lower()
            results = [
                t for t in results
                if query_lower in t.name.lower()
                or query_lower in t.description.lower()
                or any(query_lower in tag.lower() for tag in t.tags)
            ]
        results.sort(key=lambda t: t.success_rate, reverse=True)
        return results[:limit]

    def list_categories(self) -> list[TemplateCategory]:
        return list(TemplateCategory)

    def get_top(self, limit: int = 10) -> list[PromptTemplate]:
        sorted_templates = sorted(
            self._templates.values(),
            key=lambda t: (t.usage_count, t.success_rate),
            reverse=True,
        )
        return sorted_templates[:limit]

    def export(self) -> list[dict[str, Any]]:
        return [
            {
                "template_id": t.template_id,
                "name": t.name,
                "category": t.category.value,
                "template": t.template,
                "variables": t.variables,
                "description": t.description,
                "version": t.version,
                "tags": t.tags,
                "author": t.author,
                "usage_count": t.usage_count,
                "success_rate": t.success_rate,
            }
            for t in self._templates.values()
        ]

    def import_template(self, data: dict[str, Any]) -> PromptTemplate:
        template = PromptTemplate(
            template_id=data["template_id"],
            name=data["name"],
            category=TemplateCategory(data["category"]),
            template=data["template"],
            variables=data.get("variables", []),
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            tags=data.get("tags", []),
            author=data.get("author", ""),
            usage_count=data.get("usage_count", 0),
            success_rate=data.get("success_rate", 0.0),
        )
        self.add(template)
        return template


__all__ = [
    "TemplateCategory",
    "PromptTemplate",
    "PromptTemplateLibrary",
]