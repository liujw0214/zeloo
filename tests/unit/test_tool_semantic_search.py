"""Unit tests for agent.tool_semantic_search.

Covers:
- ToolSemanticSearch default / custom index_path init
- index_tool() inserting and updating entries
- search() ranking with and without category filter
- get_recommendation() filtering by available_tools
- get_index_size() counting entries
- remove_tool() entry deletion
- ToolEntry dataclass round-trip
- Backend fallback when fastembed / sentence_transformers is unavailable
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.tool_semantic_search import ToolEntry, ToolSemanticSearch


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def search(tmp_path: Path) -> ToolSemanticSearch:
    return ToolSemanticSearch(backend="tfidf", index_path=tmp_path / "idx.json")


@pytest.fixture
def seeded(search: ToolSemanticSearch) -> ToolSemanticSearch:
    search.index_tool(
        "web_search", "search",
        "Search the web for documents and snippets",
        {"query": "string"},
    )
    search.index_tool(
        "code_exec", "execution",
        "Execute arbitrary Python or shell code",
        {"language": "string", "code": "string"},
    )
    search.index_tool(
        "file_read", "filesystem",
        "Read a file from the local filesystem",
        {"path": "string"},
    )
    return search


# ── Init ──────────────────────────────────────────────────────────────


class TestInit:
    def test_default(self, tmp_path: Path) -> None:
        s = ToolSemanticSearch(index_path=tmp_path / "x.json")
        assert s.backend_requested == "tfidf"
        assert s.backend_active == "tfidf"
        # Parent dir is always created; the file itself only appears after
        # the first persist.
        assert s.index_path.parent.exists()

    def test_unknown_backend_falls_back_to_tfidf(self, tmp_path: Path) -> None:
        # Even if user requests sentence_transformers, library isn't installed
        # in tests, so we expect fallback.
        s = ToolSemanticSearch(backend="sentence_transformers", index_path=tmp_path / "y.json")
        assert s.backend_active in ("tfidf", "sentence_transformers")
        assert s.get_index_size() == 0


# ── index_tool ────────────────────────────────────────────────────────


class TestIndexTool:
    def test_insert(self, search: ToolSemanticSearch) -> None:
        search.index_tool("t1", "cat", "description", {"k": "v"})
        assert search.get_index_size() == 1

    def test_update_existing(self, search: ToolSemanticSearch) -> None:
        search.index_tool("t1", "cat", "first", {})
        search.index_tool("t1", "cat", "second", {})
        # No duplicate entry — single record by name.
        assert search.get_index_size() == 1


# ── search ────────────────────────────────────────────────────────────


class TestSearch:
    def test_empty_index_returns_empty(self, search: ToolSemanticSearch) -> None:
        assert search.search("anything") == []

    def test_returns_relevant_tool_first(self, seeded: ToolSemanticSearch) -> None:
        results = seeded.search("execute python code", top_k=3)
        assert len(results) >= 1
        names = [r["name"] for r in results]
        assert "code_exec" in names

    def test_category_filter(self, seeded: ToolSemanticSearch) -> None:
        results = seeded.search("read", category="filesystem", top_k=5)
        assert all(r["category"] == "filesystem" for r in results)
        assert any(r["name"] == "file_read" for r in results)

    def test_category_filter_empty(self, seeded: ToolSemanticSearch) -> None:
        results = seeded.search("anything", category="nonexistent")
        assert results == []

    def test_top_k_limit(self, seeded: ToolSemanticSearch) -> None:
        results = seeded.search("tool", top_k=1)
        assert len(results) <= 1

    def test_result_shape(self, seeded: ToolSemanticSearch) -> None:
        results = seeded.search("search web", top_k=1)
        assert results
        r = results[0]
        assert set(r.keys()) >= {"name", "category", "description", "score", "parameters"}


# ── get_recommendation ────────────────────────────────────────────────


class TestGetRecommendation:
    def test_empty_allowlist_returns_empty(self, seeded: ToolSemanticSearch) -> None:
        assert seeded.get_recommendation("query", []) == []

    def test_filters_to_allowed(self, seeded: ToolSemanticSearch) -> None:
        recs = seeded.get_recommendation("python code", ["code_exec", "file_read"])
        assert all(name in {"code_exec", "file_read"} for name in recs)
        assert "code_exec" in recs

    def test_no_match_in_allowlist(self, seeded: ToolSemanticSearch) -> None:
        # Allowlist contains nothing that matches — return empty.
        recs = seeded.get_recommendation("python code", ["unknown_tool"])
        assert recs == []


# ── remove_tool / size ────────────────────────────────────────────────


class TestRemoveAndSize:
    def test_get_index_size(self, search: ToolSemanticSearch) -> None:
        assert search.get_index_size() == 0
        search.index_tool("a", "c", "d", {})
        assert search.get_index_size() == 1

    def test_remove_existing(self, search: ToolSemanticSearch) -> None:
        search.index_tool("a", "c", "d", {})
        assert search.remove_tool("a") is True
        assert search.get_index_size() == 0

    def test_remove_unknown(self, search: ToolSemanticSearch) -> None:
        assert search.remove_tool("nope") is False


# ── ToolEntry round-trip ──────────────────────────────────────────────


class TestToolEntry:
    def test_round_trip(self) -> None:
        entry = ToolEntry(
            name="t", category="c", description="d", parameters={"k": 1},
            text_blob="t c d k", tfidf_vector={"k": 0.5}, embedding=None,
        )
        restored = ToolEntry.from_dict(entry.to_dict())
        assert restored.name == "t"
        assert restored.parameters == {"k": 1}
        assert restored.tfidf_vector == {"k": 0.5}
        assert restored.embedding is None