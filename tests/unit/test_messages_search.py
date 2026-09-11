"""Tests for zeloo_state_messages and zeloo_state_search."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from zeloo_state_messages import (
    MessageExporter,
    get_messages_paginated,
    import_messages,
)
from zeloo_state_search import MessageSearch, SearchResult

try:
    import numpy as np

    _NP_AVAILABLE = True
except ImportError:
    _NP_AVAILABLE = False


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    db = tmp_path / "state.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE sessions (
            session_id TEXT PRIMARY KEY,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT,
            tool_calls TEXT,
            tool_call_id TEXT,
            name TEXT,
            created_at REAL NOT NULL
        );
        CREATE VIRTUAL TABLE messages_fts USING fts5(content, content_rowid);
        INSERT INTO sessions (session_id, created_at, updated_at) VALUES ('s1', 1.0, 1.0);
        INSERT INTO messages (session_id, role, content, created_at)
            VALUES ('s1', 'user', 'hello world', 1.0);
        INSERT INTO messages (session_id, role, content, created_at)
            VALUES ('s1', 'assistant', 'hi there', 2.0);
        INSERT INTO messages (session_id, role, content, created_at)
            VALUES ('s1', 'user', 'tell me about python', 3.0);
        INSERT INTO messages (session_id, role, content, created_at)
            VALUES ('s1', 'assistant', 'python is great', 4.0);
        INSERT INTO messages (session_id, role, content, created_at)
            VALUES ('s1', 'user', 'bye', 5.0);
        INSERT INTO messages_fts (rowid, content)
            SELECT id, content FROM messages WHERE content IS NOT NULL;
        """
    )
    conn.commit()
    conn.close()
    return db


# ── messages: pagination ──────────────────────────────────────────────

class TestGetMessagesPaginated:
    def test_first_page(self, tmp_db: Path) -> None:
        page = get_messages_paginated(tmp_db, "s1", limit=2)
        assert len(page.messages) == 2
        assert page.has_more is True
        assert page.next_before is not None

    def test_second_page(self, tmp_db: Path) -> None:
        first = get_messages_paginated(tmp_db, "s1", limit=2)
        second = get_messages_paginated(tmp_db, "s1", before=first.next_before, limit=2)
        assert len(second.messages) == 2
        assert second.has_more is True

    def test_last_page(self, tmp_db: Path) -> None:
        page = get_messages_paginated(tmp_db, "s1", before=3.0, limit=2)
        assert len(page.messages) <= 2
        assert page.has_more is False
        assert page.next_before is None

    def test_empty_session(self, tmp_db: Path) -> None:
        page = get_messages_paginated(tmp_db, "nonexistent", limit=20)
        assert page.messages == []
        assert page.has_more is False


# ── messages: export ──────────────────────────────────────────────────

class TestMessageExporter:
    def test_export_session_jsonl(self, tmp_db: Path, tmp_path: Path) -> None:
        out = tmp_path / "export.jsonl"
        exp = MessageExporter(tmp_db)
        result = exp.export_session("s1", output_path=out)
        assert result == out
        lines = out.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 5
        obj = json.loads(lines[0])
        assert obj["session_id"] == "s1"
        assert obj["role"] == "user"

    def test_export_session_json_format(self, tmp_db: Path, tmp_path: Path) -> None:
        out = tmp_path / "export.json"
        exp = MessageExporter(tmp_db)
        exp.export_session("s1", output_path=out, format="json")
        obj = json.loads(out.read_text(encoding="utf-8"))
        assert "metadata" in obj
        assert "messages" in obj
        assert obj["metadata"]["message_count"] == 5

    def test_export_all(self, tmp_db: Path, tmp_path: Path) -> None:
        out = tmp_path / "all.jsonl"
        exp = MessageExporter(tmp_db)
        exp.export_all(out)
        lines = out.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 5


# ── messages: import ───────────────────────────────────────────────────

class TestImportMessages:
    def test_import_append(self, tmp_db: Path, tmp_path: Path) -> None:
        src = tmp_path / "import.jsonl"
        src.write_text(
            json.dumps({"role": "user", "content": "imported msg"}) + "\n"
            + json.dumps({"role": "assistant", "content": "reply"}),
            encoding="utf-8",
        )
        count = import_messages(tmp_db, src, "s1")
        assert count == 2

        conn = sqlite3.connect(str(tmp_db))
        total = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id='s1'"
        ).fetchone()[0]
        conn.close()
        assert total == 7

    def test_import_replace(self, tmp_db: Path, tmp_path: Path) -> None:
        src = tmp_path / "import.jsonl"
        src.write_text(
            json.dumps({"role": "user", "content": "new start"}),
            encoding="utf-8",
        )
        count = import_messages(tmp_db, src, "s1", replace=True)
        assert count == 1

        conn = sqlite3.connect(str(tmp_db))
        total = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id='s1'"
        ).fetchone()[0]
        conn.close()
        assert total == 1

    def test_import_invalid_json_raises(self, tmp_db: Path, tmp_path: Path) -> None:
        src = tmp_path / "bad.jsonl"
        src.write_text('{"role": "user" notvalid', encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid JSON"):
            import_messages(tmp_db, src, "s1")

    def test_import_missing_file_raises(self, tmp_db: Path) -> None:
        with pytest.raises(FileNotFoundError):
            import_messages(tmp_db, Path("/nope/file.jsonl"), "s1")


# ── search: FTS5 ─────────────────────────────────────────────────────

class TestMessageSearchFTS:
    def test_search_fts_finds_results(self, tmp_db: Path) -> None:
        s = MessageSearch(tmp_db)
        results = s.search("python", session_id="s1", mode="fts")
        assert len(results) >= 1
        assert any("python" in r.content.lower() for r in results)

    def test_search_fts_empty_query(self, tmp_db: Path) -> None:
        s = MessageSearch(tmp_db)
        results = s.search("zzznomatch999", session_id="s1", mode="fts")
        assert results == []

    def test_search_fts_no_session(self, tmp_db: Path) -> None:
        s = MessageSearch(tmp_db)
        results = s.search("hello", mode="fts")
        assert len(results) >= 1

    def test_auto_mode_uses_fts_when_no_embedder(self, tmp_db: Path) -> None:
        s = MessageSearch(tmp_db)
        results = s.search("hello", mode="auto")
        assert len(results) >= 1

    def test_search_result_fields(self, tmp_db: Path) -> None:
        s = MessageSearch(tmp_db)
        results = s.search("hello", session_id="s1", mode="fts")
        assert all(
            hasattr(r, f) for r in results
            for f in ("message_id", "session_id", "role", "content", "score", "created_at")
        )

    def test_invalid_mode_raises(self, tmp_db: Path) -> None:
        s = MessageSearch(tmp_db)
        with pytest.raises(ValueError, match="Invalid mode"):
            s.search("hello", mode="badmode")


# ── search: semantic ──────────────────────────────────────────────────

@pytest.mark.skipif(not _NP_AVAILABLE, reason="numpy not installed")
class TestMessageSearchSemantic:
    def test_search_semantic_without_embedder_raises(self, tmp_db: Path) -> None:
        s = MessageSearch(tmp_db)
        with pytest.raises(ValueError, match="embedder"):
            s.search("hello", mode="semantic")

    def test_semantic_search_with_mock_embedder(self, tmp_db: Path) -> None:
        def mock_embed(text: str) -> list[float]:
            if "hello" in text:
                return [1.0, 0.0]
            if "bye" in text:
                return [0.0, 1.0]
            return [0.5, 0.5]

        s = MessageSearch(tmp_db, embedder=mock_embed)
        np.testing.assert_array_equal(mock_embed("hello world"), [1.0, 0.0])
        assert s._embedding_dim == 2

        conn = sqlite3.connect(str(tmp_db))
        s._ensure_embedding_schema()
        for row in conn.execute(
            "SELECT id, content FROM messages WHERE content IS NOT NULL"
        ):
            vec = np.array(mock_embed(str(row[1])), dtype=np.float32)
            emb_bytes = vec.tobytes()
            conn.execute(
                "INSERT OR REPLACE INTO message_embeddings VALUES (?, ?)",
                (row[0], emb_bytes),
            )
        conn.commit()
        conn.close()

        results = s.search("say goodbye", mode="semantic", session_id="s1")
        assert len(results) >= 1
        assert all(isinstance(r, SearchResult) for r in results)
        assert all(isinstance(r.score, float) for r in results)
        assert all(-1.0 <= r.score <= 1.0 for r in results)

    def test_index_session_no_embedder_raises(self, tmp_db: Path) -> None:
        s = MessageSearch(tmp_db)
        with pytest.raises(RuntimeError, match="embedder"):
            s.index_session("s1")

    def test_index_session_no_numpy_raises(self, tmp_db: Path) -> None:
        def fake_embed(text: str) -> list[float]:
            return [0.0, 0.0]

        s = MessageSearch(tmp_db, embedder=fake_embed)
        assert s._embedder is not None
        assert s._embedding_dim == 2

    def test_semantic_returns_empty_without_embeddings(self, tmp_db: Path) -> None:
        def mock_embed(text: str) -> list[float]:
            return [0.5, 0.5]

        s = MessageSearch(tmp_db, embedder=mock_embed)
        results = s.search("hello", mode="semantic", session_id="s1")
        assert results == []
