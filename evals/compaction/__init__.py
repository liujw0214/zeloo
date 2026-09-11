"""Compaction evaluation suite.

Measures the impact of context compression on conversation accuracy.
Compares model responses before and after `context_compressor`/`compression_facade`.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CompactionCase:
    """One conversation snippet with a reference question and answer."""
    name: str
    conversation: list[dict[str, str]]
    question: str
    reference_keywords: list[str]
    expected_min_keyword_hits: int = 1


@dataclass
class CompactionCaseResult:
    name: str
    pre_compression_keywords_hit: int
    post_compression_keywords_hit: int
    retention_rate: float
    passed: bool


@dataclass
class CompactionEvalReport:
    total: int
    passed: int
    avg_retention_rate: float
    results: list[CompactionCaseResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_cases() -> list[CompactionCase]:
    """Built-in evaluation cases for context compaction."""
    return [
        CompactionCase(
            name="factual_recall_short",
            conversation=[
                {"role": "user", "content": "Zeloo 是什么？"},
                {"role": "assistant", "content": "Zeloo 是一个自托管、自进化的 AI Agent 运行时框架。"},
                {"role": "user", "content": "它支持哪些模型？"},
                {"role": "assistant", "content": "支持 OpenAI、Anthropic、Gemini、DeepSeek 等多种模型。"},
            ],
            question="Zeloo 是什么类型的框架？",
            reference_keywords=["自托管", "Agent", "运行时"],
            expected_min_keyword_hits=2,
        ),
        CompactionCase(
            name="factual_recall_medium",
            conversation=[
                {"role": "user", "content": "Python 3.12 有哪些新特性？"},
                {"role": "assistant", "content": "Python 3.12 引入了 f-string 改进、类型注解新语法、错误信息优化、PEP 695 类型参数等。"},
                {"role": "user", "content": "性能怎么样？"},
                {"role": "assistant", "content": "Python 3.12 相比 3.11 有约 5% 的性能提升。"},
            ],
            question="Python 3.12 性能如何？",
            reference_keywords=["3.11", "5%", "性能"],
            expected_min_keyword_hits=1,
        ),
        CompactionCase(
            name="long_conversation_facts",
            conversation=[
                {"role": "user", "content": "项目代号是什么？"},
                {"role": "assistant", "content": "项目代号是 Zeloo。"},
                {"role": "user", "content": "数据库用什么？"},
                {"role": "assistant", "content": "数据库使用 SQLite，配合 FTS5 全文检索。"},
                {"role": "user", "content": "前端框架？"},
                {"role": "assistant", "content": "暂无独立前端，使用 Docusaurus 构建文档站点。"},
                {"role": "user", "content": "部署方式？"},
                {"role": "assistant", "content": "支持 Docker 和 NixOS 双部署方式。"},
            ],
            question="数据库使用什么？",
            reference_keywords=["SQLite", "FTS5"],
            expected_min_keyword_hits=1,
        ),
    ]


def _keyword_hits(text: str, keywords: list[str]) -> int:
    """Count how many of the keywords appear in the text (case-insensitive)."""
    lower = text.lower()
    return sum(1 for k in keywords if k.lower() in lower)


def _compress_messages(messages: list[dict[str, str]], target_ratio: float = 0.5) -> list[dict[str, str]]:
    """Truncate conversation to a target ratio, preserving first and last turns.

    This is a simple baseline that mimics what context compressors do:
    keep the first message (initial context) and the last N messages (recent context).
    """
    if not messages:
        return messages
    n = max(2, int(len(messages) * target_ratio))
    if n >= len(messages):
        return messages
    head = messages[:1]
    tail = messages[-(n - 1):]
    return head + tail


def run_cases(
    answer_fn: Any | None = None,
    cases: list[CompactionCase] | None = None,
    compress_fn: Any = _compress_messages,
) -> CompactionEvalReport:
    """Run each compaction case.

    Args:
        answer_fn: optional callable(question, messages) -> str; if None, uses keyword matching
            against the raw message content as a stand-in.
        cases: list of cases; defaults to default_cases().
        compress_fn: function(messages) -> compressed messages.
    """
    cases = cases or default_cases()
    results: list[CompactionCaseResult] = []

    for case in cases:
        pre_text = " ".join(m.get("content", "") for m in case.conversation)
        compressed = compress_fn(case.conversation)
        post_text = " ".join(m.get("content", "") for m in compressed)

        if answer_fn is not None:
            pre_answer = answer_fn(case.question, case.conversation)
            post_answer = answer_fn(case.question, compressed)
            pre_hits = _keyword_hits(pre_answer, case.reference_keywords)
            post_hits = _keyword_hits(post_answer, case.reference_keywords)
        else:
            pre_hits = _keyword_hits(pre_text, case.reference_keywords)
            post_hits = _keyword_hits(post_text, case.reference_keywords)

        retention = (post_hits / pre_hits) if pre_hits > 0 else 1.0
        passed = post_hits >= case.expected_min_keyword_hits

        results.append(CompactionCaseResult(
            name=case.name,
            pre_compression_keywords_hit=pre_hits,
            post_compression_keywords_hit=post_hits,
            retention_rate=round(retention, 3),
            passed=passed,
        ))

    total = len(results)
    passed = sum(1 for r in results if r.passed)
    avg_ret = sum(r.retention_rate for r in results) / total if total > 0 else 0.0
    return CompactionEvalReport(
        total=total,
        passed=passed,
        avg_retention_rate=round(avg_ret, 3),
        results=results,
    )


def save_report(report: CompactionEvalReport, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
