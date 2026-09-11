"""Optimization report generator — produce analytics and recommendations."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class OptimizationReport:
    """Comprehensive optimization analysis report."""

    report_id: str
    original_prompt: str
    optimized_prompt: str
    timestamp: float
    techniques_used: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    cost_estimate: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "timestamp": self.timestamp,
            "original_prompt": self.original_prompt,
            "optimized_prompt": self.optimized_prompt,
            "techniques_used": self.techniques_used,
            "metrics": self.metrics,
            "recommendations": self.recommendations,
            "warnings": self.warnings,
            "cost_estimate": self.cost_estimate,
            "metadata": self.metadata,
        }

    def to_markdown(self) -> str:
        """Generate human-readable Markdown report."""
        lines = [
            "# Prompt Optimization Report",
            "",
            f"**Report ID:** `{self.report_id}`  ",
            f"**Timestamp:** {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.timestamp))}  ",  # noqa: E501
            "",
            "## Metrics",
            "",
        ]
        for key, value in self.metrics.items():
            lines.append(f"- **{key}:** {value}")

        lines.extend([
            "",
            "## Techniques Applied",
            "",
        ])
        for technique in self.techniques_used:
            lines.append(f"- {technique}")

        lines.extend([
            "",
            "## Recommendations",
            "",
        ])
        if self.recommendations:
            for rec in self.recommendations:
                lines.append(f"- {rec}")
        else:
            lines.append("- No additional recommendations")

        if self.warnings:
            lines.extend([
                "",
                "## Warnings",
                "",
            ])
            for warning in self.warnings:
                lines.append(f"- ⚠️  {warning}")

        if self.cost_estimate:
            lines.extend([
                "",
                "## Cost Estimate",
                "",
            ])
            for key, value in self.cost_estimate.items():
                lines.append(f"- **{key}:** ${value:.4f}")

        lines.extend([
            "",
            "## Optimized Prompt",
            "",
            "```",
            self.optimized_prompt,
            "```",
            "",
        ])
        return "\n".join(lines)


class OptimizationReportGenerator:
    """Generate comprehensive optimization reports."""

    def __init__(self) -> None:
        self._history: list[OptimizationReport] = []

    def create_report(
        self,
        original_prompt: str,
        optimized_prompt: str,
        techniques: list[str],
        metrics: dict[str, Any] | None = None,
        recommendations: list[str] | None = None,
        warnings: list[str] | None = None,
        cost_estimate: dict[str, float] | None = None,
    ) -> OptimizationReport:
        report_id = f"opt_{int(time.time() * 1000)}"
        report = OptimizationReport(
            report_id=report_id,
            original_prompt=original_prompt,
            optimized_prompt=optimized_prompt,
            timestamp=time.time(),
            techniques_used=techniques,
            metrics=metrics or {},
            recommendations=recommendations or [],
            warnings=warnings or [],
            cost_estimate=cost_estimate or {},
        )
        self._history.append(report)
        logger.info("Generated optimization report %s", report_id)
        return report

    def get_history(self, limit: int = 20) -> list[OptimizationReport]:
        return self._history[-limit:]

    def export_json(self, report: OptimizationReport) -> str:
        return json.dumps(report.to_dict(), indent=2, ensure_ascii=False)

    def generate_recommendations(
        self,
        original_tokens: int,
        compressed_tokens: int,
        safety_threat_level: str,
        variant_count: int,
    ) -> list[str]:
        """Generate optimization recommendations based on metrics."""
        recs: list[str] = []
        if compressed_tokens > 0:
            ratio = compressed_tokens / original_tokens
            if ratio > 0.8:
                recs.append(
                    "Compression ratio is high; consider more aggressive techniques"
                )
            elif ratio < 0.3:
                recs.append(
                    "Excellent compression achieved; verify quality preservation"
                )
        if safety_threat_level in ("high", "critical"):
            recs.append(
                "Safety threats detected; consider rejecting or sanitizing prompt"
            )
        if variant_count < 3:
            recs.append(
                "Generate more variants for better A/B testing coverage"
            )
        return recs


__all__ = [
    "OptimizationReport",
    "OptimizationReportGenerator",
]