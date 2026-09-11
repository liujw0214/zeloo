"""Token accounting evaluation suite.

Measures the accuracy of tiktoken-based token counting across diverse inputs.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class TokenCountCase:
    name: str
    text: str
    expected_range: tuple[int, int]
    model: str = "cl100k_base"


@dataclass
class TokenCountResult:
    name: str
    expected_min: int
    expected_max: int
    actual: int
    passed: bool


@dataclass
class TokenAccountingReport:
    total: int
    passed: int
    avg_actual: float
    results: list[TokenCountResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_cases() -> list[TokenCountCase]:
    return [
        TokenCountCase(name="empty", text="", expected_range=(0, 0)),
        TokenCountCase(name="short", text="Hello world.", expected_range=(2, 4)),
        TokenCountCase(name="medium", text="The quick brown fox jumps over the lazy dog. " * 5, expected_range=(45, 60)),
        TokenCountCase(name="chinese", text="你好世界，Zeloo 智能体框架。", expected_range=(8, 18)),
        TokenCountCase(name="code", text="def hello(name: str) -> str:\n    return f'hi {name}'\n", expected_range=(15, 25)),
        TokenCountCase(name="json", text='{"key": "value", "n": 42, "items": [1, 2, 3]}', expected_range=(15, 30)),
    ]


def run_cases(
    counter_fn: Any,
    cases: list[TokenCountCase] | None = None,
) -> TokenAccountingReport:
    """Run token counting accuracy tests.

    Args:
        counter_fn: callable(text, model) -> int.
        cases: list of cases; defaults to default_cases().
    """
    cases = cases or default_cases()
    results: list[TokenCountResult] = []

    for case in cases:
        try:
            actual = int(counter_fn(case.text, case.model))
            passed = case.expected_range[0] <= actual <= case.expected_range[1]
            results.append(TokenCountResult(
                name=case.name,
                expected_min=case.expected_range[0],
                expected_max=case.expected_range[1],
                actual=actual,
                passed=passed,
            ))
        except Exception:
            results.append(TokenCountResult(
                name=case.name,
                expected_min=case.expected_range[0],
                expected_max=case.expected_range[1],
                actual=-1,
                passed=False,
            ))

    total = len(results)
    passed = sum(1 for r in results if r.passed)
    avg = sum(r.actual for r in results if r.actual >= 0) / max(1, sum(1 for r in results if r.actual >= 0))
    return TokenAccountingReport(
        total=total,
        passed=passed,
        avg_actual=round(avg, 2),
        results=results,
    )


def save_report(report: TokenAccountingReport, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
