"""Read-tool evaluation suite.

Verifies that file_read returns expected content from controlled fixtures
and properly enforces path safety.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ReadToolCase:
    name: str
    fixture_path: str
    expected_substring: str | None = None
    expected_line_count: int | None = None
    should_succeed: bool = True
    is_path_violation: bool = False


@dataclass
class ReadToolCaseResult:
    name: str
    passed: bool
    output_chars: int = 0
    error: str | None = None


@dataclass
class ReadToolEvalReport:
    total: int
    passed: int
    failed: int
    pass_rate: float
    results: list[ReadToolCaseResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_cases(tmp_dir: Path | None = None) -> list[ReadToolCase]:
    """Built-in read-tool evaluation cases.

    Args:
        tmp_dir: directory to use for fixtures; created if not provided.
    """
    if tmp_dir is None:
        tmp_dir = Path.cwd() / ".evals_readtool_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    f1 = tmp_dir / "sample.txt"
    if not f1.exists():
        f1.write_text("Hello Zeloo\nLine 2\nLine 3 with keyword FACT_TOKEN\n", encoding="utf-8")
    f2 = tmp_dir / "multiline.py"
    if not f2.exists():
        f2.write_text("def hello():\n    print('hi')\n", encoding="utf-8")

    return [
        ReadToolCase(
            name="basic_read",
            fixture_path=str(f1),
            expected_substring="Zeloo",
            should_succeed=True,
        ),
        ReadToolCase(
            name="keyword_present",
            fixture_path=str(f1),
            expected_substring="FACT_TOKEN",
            should_succeed=True,
        ),
        ReadToolCase(
            name="multiline_read",
            fixture_path=str(f2),
            expected_substring="hello",
            should_succeed=True,
        ),
        ReadToolCase(
            name="line_count_check",
            fixture_path=str(f1),
            expected_line_count=3,
            should_succeed=True,
        ),
        ReadToolCase(
            name="path_traversal_blocked",
            fixture_path="../../../etc/passwd",
            should_succeed=False,
            is_path_violation=True,
        ),
        ReadToolCase(
            name="nonexistent_file",
            fixture_path=str(tmp_dir / "does_not_exist.txt"),
            should_succeed=False,
        ),
    ]


def run_cases(
    reader_fn: Any,
    cases: list[ReadToolCase] | None = None,
    tmp_dir: Path | None = None,
) -> ReadToolEvalReport:
    """Run each read case against a reader function.

    Args:
        reader_fn: callable(path: str) -> str (raises on error).
        cases: list of cases; defaults to default_cases().
        tmp_dir: directory for fixtures.
    """
    cases = cases or default_cases(tmp_dir)
    results: list[ReadToolCaseResult] = []

    for case in cases:
        try:
            content = reader_fn(case.fixture_path)
            if not case.should_succeed:
                results.append(ReadToolCaseResult(
                    name=case.name,
                    passed=False,
                    error="expected failure but got success",
                    output_chars=len(content or ""),
                ))
                continue

            passed = True
            err: str | None = None
            if case.expected_substring and case.expected_substring not in content:
                passed = False
                err = f"missing substring: {case.expected_substring!r}"
            if case.expected_line_count is not None:
                lines = content.splitlines()
                if len(lines) != case.expected_line_count:
                    passed = False
                    err = f"expected {case.expected_line_count} lines, got {len(lines)}"

            results.append(ReadToolCaseResult(
                name=case.name,
                passed=passed,
                output_chars=len(content or ""),
                error=err,
            ))
        except Exception as e:
            passed = case.should_succeed is False
            results.append(ReadToolCaseResult(
                name=case.name,
                passed=passed,
                error=str(e) if not passed else None,
            ))

    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed
    return ReadToolEvalReport(
        total=total,
        passed=passed,
        failed=failed,
        pass_rate=passed / total if total > 0 else 0.0,
        results=results,
    )


def save_report(report: ReadToolEvalReport, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
