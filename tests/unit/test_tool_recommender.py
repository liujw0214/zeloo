"""Tests for agent.tool_recommender."""

from __future__ import annotations

from agent.tool_recommender import ToolRecommender


class TestKeywordMatch:
    def test_file_read_keyword_match(self) -> None:
        rec = ToolRecommender().recommend("please read this file")
        assert rec.primary_tool.tool_name == "file_read"

    def test_shell_keyword_match(self) -> None:
        rec = ToolRecommender().recommend("execute the shell command")
        assert rec.primary_tool.tool_name == "shell"

    def test_web_search_match(self) -> None:
        rec = ToolRecommender().recommend("search for python tutorials")
        assert rec.primary_tool.tool_name == "web_search"

    def test_code_exec_match(self) -> None:
        rec = ToolRecommender().recommend("compute and run a python script")
        assert rec.primary_tool.tool_name == "code_exec"


class TestFallback:
    def test_no_match_returns_default(self) -> None:
        rec = ToolRecommender().recommend("blah blah random words")
        assert rec.primary_tool.tool_name == "reasoning"
        assert rec.confidence < 0.5


class TestConfidenceAlgorithm:
    def test_confidence_is_not_always_half(self) -> None:
        """Regression: previous implementation always returned 0.5 for the
        primary recommendation because ``primary_score / max(scores) = 1``
        was divided by an extra factor of 2.
        """
        rec = ToolRecommender().recommend("read this file")
        assert rec.confidence != 0.5

    def test_strong_match_yields_higher_confidence_than_weak(self) -> None:
        weak = ToolRecommender().recommend("file read something")
        strong = ToolRecommender().recommend(
            "please read open show view this document file"
        )
        assert strong.confidence > weak.confidence

    def test_confidence_is_bounded_zero_one(self) -> None:
        for desc in ["read file", "compute python", "search web", "shell bash"]:
            conf = ToolRecommender().recommend(desc).confidence
            assert 0.0 <= conf <= 1.0


class TestUsageHistory:
    def test_usage_history_boosts_score(self) -> None:
        r = ToolRecommender()
        # Record many uses for file_read to give it a usage bonus.
        for _ in range(50):
            r.record_usage("file_read")
        rec = r.recommend("read the file")
        assert rec.primary_tool.tool_name == "file_read"
        reasons = rec.primary_tool.reasons
        assert any("historical_usage" in s for s in reasons)


class TestDescriptionOverlap:
    def test_registered_tool_overlap_ranks_high(self) -> None:
        r = ToolRecommender()
        r.register_tool(
            name="my_special_tool",
            description="convert markdown to html safely",
            keywords=["markdown"],
            category="general",
        )
        rec = r.recommend("convert markdown to html")
        assert rec.primary_tool.tool_name == "my_special_tool"

    def test_registered_tool_without_match_does_not_win(self) -> None:
        r = ToolRecommender()
        r.register_tool(
            name="pdf_tool",
            description="create PDF documents",
            keywords=["pdf"],
        )
        rec = r.recommend("read a text file")
        # file_read has built-in keyword match — pdf_tool does not.
        assert rec.primary_tool.tool_name == "file_read"


class TestTaskTypeInference:
    def test_information_retrieval(self) -> None:
        assert ToolRecommender().recommend("read the file").task_type == "information_retrieval"

    def test_code_modification(self) -> None:
        assert ToolRecommender().recommend("edit and write code").task_type == "code_modification"

    def test_research(self) -> None:
        assert ToolRecommender().recommend("search the docs").task_type == "research"

    def test_general_fallback(self) -> None:
        assert ToolRecommender().recommend("blah").task_type == "general"


class TestAlternatives:
    def test_alternatives_count_top_k(self) -> None:
        rec = ToolRecommender().recommend("read or write a file", top_k=3)
        assert len(rec.alternatives) <= 3
        # All alternatives differ from primary
        names = {a.tool_name for a in rec.alternatives}
        assert rec.primary_tool.tool_name not in names

    def test_alternatives_sorted_by_score(self) -> None:
        rec = ToolRecommender().recommend("read or write a file", top_k=5)
        scores = [a.score for a in rec.alternatives]
        assert scores == sorted(scores, reverse=True)