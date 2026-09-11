"""Unit tests for agent.reflection_engine.

Covers:
- ReflectionEngine init with each strategy
- async critique() returning ReflectionVerdict under each strategy
- record_decision() / get_critique_stats() aggregation
- ReflectionVerdict dataclass shape and to_dict
- hedge / empty / risky-tool cheap_local detection
- llm_judge fallback when callable missing or fails
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent.reflection_engine import ReflectionEngine, ReflectionVerdict


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def engine(tmp_path: Path) -> ReflectionEngine:
    return ReflectionEngine(
        strategy="cheap_local",
        stats_path=tmp_path / "stats.json",
    )


@pytest.fixture
def assistant_messages() -> list[dict[str, Any]]:
    return [
        {"role": "user", "content": "What is 2+2?"},
        {"role": "assistant", "content": "The answer is four, confirmed by basic arithmetic."},
    ]


# ── Init ──────────────────────────────────────────────────────────────


class TestInit:
    def test_default_init(self, tmp_path: Path) -> None:
        engine = ReflectionEngine(stats_path=tmp_path / "x.json")
        assert engine.strategy == "cheap_local"
        assert engine.reroll_threshold == 0.4

    def test_invalid_strategy_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            ReflectionEngine(strategy="bogus", stats_path=tmp_path / "x.json")

    def test_persists_path(self, tmp_path: Path) -> None:
        engine = ReflectionEngine(stats_path=tmp_path / "p.json")
        assert engine.stats_path == tmp_path / "p.json"
        assert engine.stats_path.parent.exists()


# ── strategy "none" ────────────────────────────────────────────────────


class TestNoneStrategy:
    @pytest.mark.asyncio
    async def test_short_circuits(self, tmp_path: Path) -> None:
        engine = ReflectionEngine(strategy="none", stats_path=tmp_path / "n.json")
        verdict = await engine.critique([])
        assert isinstance(verdict, ReflectionVerdict)
        assert verdict.should_reroll is False
        assert verdict.confidence == 1.0
        assert verdict.strategy == "none"


# ── strategy "cheap_local" ────────────────────────────────────────────


class TestCheapLocalStrategy:
    @pytest.mark.asyncio
    async def test_high_quality_passes(self, engine: ReflectionEngine,
                                       assistant_messages: list[dict[str, Any]]) -> None:
        verdict = await engine.critique(assistant_messages, tools_used=["search"])
        assert verdict.strategy == "cheap_local"
        # No hedge phrases, non-empty → confidence stays high.
        assert verdict.confidence >= 0.8
        assert verdict.should_reroll is False

    @pytest.mark.asyncio
    async def test_detects_hedge_phrase(self, engine: ReflectionEngine) -> None:
        msgs = [{"role": "assistant", "content": "I'm not sure, I don't know the answer."}]
        verdict = await engine.critique(msgs)
        # Should detect hedge markers and lower confidence.
        assert any("hedge" in r.lower() for r in verdict.reasons)
        assert verdict.confidence < 1.0

    @pytest.mark.asyncio
    async def test_detects_empty_response(self, engine: ReflectionEngine) -> None:
        msgs = [{"role": "assistant", "content": ""}]
        verdict = await engine.critique(msgs)
        assert any("empty" in r.lower() for r in verdict.reasons)
        # Empty response drops confidence by 0.5; with default threshold 0.4
        # the verdict signals low confidence but the engine still does not
        # request reroll unless confidence < threshold.
        assert verdict.confidence <= 0.5

    @pytest.mark.asyncio
    async def test_detects_risky_tool(self, engine: ReflectionEngine) -> None:
        msgs = [{"role": "assistant", "content": "ok"}]
        verdict = await engine.critique(msgs, tools_used=["delete_database"])
        assert any("high-risk" in r.lower() for r in verdict.reasons)
        assert verdict.confidence < 1.0

    @pytest.mark.asyncio
    async def test_no_assistant_message(self, engine: ReflectionEngine) -> None:
        verdict = await engine.critique([{"role": "user", "content": "hi"}])
        # No assistant message → conservative confidence.
        assert verdict.confidence == 0.5

    @pytest.mark.asyncio
    async def test_short_response_warns(self, engine: ReflectionEngine) -> None:
        msgs = [{"role": "assistant", "content": "ok"}]  # < 20 chars
        verdict = await engine.critique(msgs)
        assert any("short" in r.lower() for r in verdict.reasons)


# ── strategy "llm_judge" ──────────────────────────────────────────────


class TestLLMJudgeStrategy:
    @pytest.mark.asyncio
    async def test_no_judge_falls_back(self, tmp_path: Path) -> None:
        engine = ReflectionEngine(
            strategy="llm_judge", llm_judge=None, stats_path=tmp_path / "j.json"
        )
        msgs = [{"role": "assistant", "content": "high quality answer"}]
        verdict = await engine.critique(msgs)
        # The engine's strategy label is preserved on the verdict object
        # (the underlying fallback uses cheap_local heuristics).
        assert verdict.strategy == "llm_judge"
        # But confidence / reasons still come from the cheap_local path.
        assert verdict.confidence >= 0.8

    @pytest.mark.asyncio
    async def test_sync_judge_invocation(self, tmp_path: Path) -> None:
        def judge(prompt: str) -> str:
            return '{"confidence": 0.9, "should_reroll": false, "reasons": ["ok"], "suggested_fix": null}'

        engine = ReflectionEngine(
            strategy="llm_judge", llm_judge=judge, stats_path=tmp_path / "j.json"
        )
        msgs = [{"role": "assistant", "content": "answer"}]
        verdict = await engine.critique(msgs)
        assert verdict.confidence == 0.9
        assert verdict.should_reroll is False

    @pytest.mark.asyncio
    async def test_async_judge_invocation(self, tmp_path: Path) -> None:
        async def judge(prompt: str) -> str:
            return '{"confidence": 0.2, "should_reroll": true, "reasons": ["bad"], "suggested_fix": "redo"}'

        engine = ReflectionEngine(
            strategy="llm_judge", llm_judge=judge, stats_path=tmp_path / "j.json"
        )
        verdict = await engine.critique([{"role": "assistant", "content": "x"}])
        assert verdict.confidence == 0.2
        assert verdict.should_reroll is True
        assert verdict.suggested_fix == "redo"

    @pytest.mark.asyncio
    async def test_judge_garbage_falls_back(self, tmp_path: Path) -> None:
        def judge(prompt: str) -> str:
            return "totally not json"

        engine = ReflectionEngine(
            strategy="llm_judge", llm_judge=judge, stats_path=tmp_path / "j.json"
        )
        verdict = await engine.critique([{"role": "assistant", "content": "answer"}])
        # JSON parse failed → degrades to cheap_local path, label is still
        # the engine's strategy.
        assert verdict.strategy == "llm_judge"


# ── record / stats ────────────────────────────────────────────────────


class TestRecordAndStats:
    def test_initial_stats(self, engine: ReflectionEngine) -> None:
        stats = engine.get_critique_stats()
        assert stats["total"] == 0
        assert stats["acceptance_rate"] == 0.0

    def test_record_decision_updates_stats(self, engine: ReflectionEngine) -> None:
        verdict = ReflectionVerdict(should_reroll=False, confidence=0.9, reasons=[])
        engine.record_decision(verdict, accepted=True)
        engine.record_decision(verdict, accepted=False)
        stats = engine.get_critique_stats()
        assert stats["total"] == 2
        assert stats["accepted"] == 1
        assert stats["rejected"] == 1
        assert stats["acceptance_rate"] == 0.5
        assert stats["avg_confidence"] == 0.9

    def test_record_decision_persists(self, tmp_path: Path) -> None:
        engine = ReflectionEngine(stats_path=tmp_path / "p.json")
        engine.record_decision(ReflectionVerdict(should_reroll=False, confidence=0.8), accepted=True)
        # Reload from disk to ensure persistence path is hit.
        engine2 = ReflectionEngine(stats_path=tmp_path / "p.json")
        assert engine2.get_critique_stats()["total"] == 1


# ── ReflectionVerdict dataclass ───────────────────────────────────────


class TestReflectionVerdict:
    def test_to_dict(self) -> None:
        v = ReflectionVerdict(
            should_reroll=True, confidence=0.3,
            reasons=["x"], suggested_fix="fix it", strategy="cheap_local",
        )
        d = v.to_dict()
        assert d["should_reroll"] is True
        assert d["confidence"] == 0.3
        assert d["reasons"] == ["x"]
        assert d["suggested_fix"] == "fix it"
        assert d["strategy"] == "cheap_local"

    def test_defaults(self) -> None:
        v = ReflectionVerdict(should_reroll=False, confidence=1.0)
        assert v.reasons == []
        assert v.suggested_fix is None
        assert v.strategy == "none"
        assert v.critiqued_at > 0