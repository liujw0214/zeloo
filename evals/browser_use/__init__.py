"""Browser-use evaluation suite.

Evaluates correctness of the 11 browser tools by replaying canned scenarios
against the in-process tool implementations and measuring pass rates.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class BrowserScenario:
    name: str
    tool: str
    args: dict[str, Any]
    expected_keys: list[str] = field(default_factory=list)
    expected_pattern: str | None = None
    should_succeed: bool = True


@dataclass
class BrowserScenarioResult:
    name: str
    tool: str
    passed: bool
    error: str | None = None
    duration_ms: float = 0.0
    output_keys: list[str] = field(default_factory=list)


@dataclass
class BrowserEvalReport:
    total: int
    passed: int
    failed: int
    pass_rate: float
    avg_duration_ms: float
    results: list[BrowserScenarioResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


def default_scenarios() -> list[BrowserScenario]:
    """Built-in evaluation scenarios for browser tools."""
    return [
        BrowserScenario(
            name="screenshot_basic",
            tool="browser_screenshot",
            args={"url": "https://example.com"},
            expected_keys=["status", "path"],
        ),
        BrowserScenario(
            name="browser_navigate",
            tool="browser_navigate",
            args={"url": "https://example.com"},
            expected_keys=["status"],
        ),
        BrowserScenario(
            name="browser_click",
            tool="browser_click",
            args={"selector": "a", "index": 0},
            expected_keys=["status"],
        ),
        BrowserScenario(
            name="browser_type",
            tool="browser_type",
            args={"selector": "input", "text": "hello"},
            expected_keys=["status"],
        ),
        BrowserScenario(
            name="browser_extract",
            tool="browser_extract",
            args={"selector": "h1"},
            expected_keys=["elements"],
        ),
        BrowserScenario(
            name="browser_scroll",
            tool="browser_scroll",
            args={"direction": "down", "amount": 300},
            expected_keys=["status"],
        ),
        BrowserScenario(
            name="browser_back",
            tool="browser_back",
            args={},
            expected_keys=["status"],
        ),
        BrowserScenario(
            name="browser_forward",
            tool="browser_forward",
            args={},
            expected_keys=["status"],
        ),
        BrowserScenario(
            name="browser_refresh",
            tool="browser_refresh",
            args={},
            expected_keys=["status"],
        ),
        BrowserScenario(
            name="browser_get_url",
            tool="browser_get_url",
            args={},
            expected_keys=["url"],
        ),
        BrowserScenario(
            name="browser_close",
            tool="browser_close",
            args={},
            expected_keys=["status"],
        ),
    ]


def run_scenarios(
    tool_runner: Callable[[str, dict[str, Any]], dict[str, Any]],
    scenarios: list[BrowserScenario] | None = None,
) -> BrowserEvalReport:
    """Run each scenario against a tool_runner function.

    Args:
        tool_runner: callable(tool_name, args) -> result dict.
        scenarios: list of BrowserScenario; defaults to default_scenarios().

    Returns:
        BrowserEvalReport with pass/fail statistics.
    """
    import time

    scenarios = scenarios or default_scenarios()
    results: list[BrowserScenarioResult] = []
    total_duration = 0.0

    for sc in scenarios:
        t0 = time.perf_counter()
        try:
            output = tool_runner(sc.tool, sc.args) or {}
            elapsed = (time.perf_counter() - t0) * 1000.0
            total_duration += elapsed

            if sc.should_succeed:
                missing = [k for k in sc.expected_keys if k not in output]
                passed = len(missing) == 0
                err = f"missing keys: {missing}" if not passed else None
            else:
                passed = "error" in output or output.get("status") == "error"
                err = None

            results.append(BrowserScenarioResult(
                name=sc.name,
                tool=sc.tool,
                passed=passed,
                error=err,
                duration_ms=elapsed,
                output_keys=sorted(output.keys()),
            ))
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000.0
            total_duration += elapsed
            results.append(BrowserScenarioResult(
                name=sc.name,
                tool=sc.tool,
                passed=sc.should_succeed is False,
                error=str(e),
                duration_ms=elapsed,
            ))

    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed
    return BrowserEvalReport(
        total=total,
        passed=passed,
        failed=failed,
        pass_rate=passed / total if total > 0 else 0.0,
        avg_duration_ms=total_duration / total if total > 0 else 0.0,
        results=results,
    )


def save_report(report: BrowserEvalReport, path: str | Path) -> None:
    """Save evaluation report to a JSON file."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
