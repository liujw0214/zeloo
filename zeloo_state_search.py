"""Zeloo state — full-text and semantic message search.

Provides two search backends:
* **FTS5** — always available; keyword/phrase search using SQLite FTS5.
* **Embedding** — optional; cosine-similarity search over pre-computed vectors.
  Requires ``numpy``. If not installed, the class logs a warning at init and
  all semantic operations raise :exc:`ImportError`.

Usage::

    from pathlib import Path
    from zeloo_state_search import MessageSearch

    search = MessageSearch(Path("~/.Zeloo/state.db"))
    # Keyword search (always works)
    results = search.search("how do I configure the terminal", session_id="s1")
    # Semantic search (requires numpy + embedder)
    results = search.search(
        "configure terminal backend", session_id="s1", mode="semantic"
    )
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import numpy as np

    _NP_AVAILABLE = True
except ImportError:
    _NP_AVAILABLE = False
    np = None  # type: ignore[assignment]


@dataclass
class SearchResult:
    """A single search result."""

    message_id: int
    session_id: str
    role: str
    content: str
    score: float
    created_at: float


class MessageSearch:
    """Unified message search backed by FTS5 and optional embeddings."""

    def __init__(
        self,
        db_path: Path,
        embedder: Callable[[str], list[float]] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self._embedder = embedder
        self._embedding_dim: int | None = None

        if self._embedder is not None and not _NP_AVAILABLE:
            logger.warning(
                "numpy is not installed; semantic search is disabled. "
                "Install it with: pip install numpy"
            )
            self._embedder = None
            return

        if self._embedder is not None:
            try:
                sample = self._embedder("init")
                self._embedding_dim = len(sample)
                self._ensure_embedding_schema()
            except Exception as exc:
                logger.warning(
                    "Embedder failed initialisation (%s); disabling semantic search.",
                    exc,
                )
                self._embedder = None
                self._embedding_dim = None

    def search(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 20,
        mode: str = "auto",
    ) -> list[SearchResult]:
        """Search messages.

        Args:
            query: Search query string.
            session_id: Optional session to restrict results to. If ``None``,
                searches across all sessions.
            limit: Maximum number of results to return.
            mode: One of ``"fts"`` (keyword search), ``"semantic"`` (embedding
                similarity), or ``"auto"`` (semantic if an embedder is
                configured, otherwise FTS).

        Returns:
            A list of :class:`SearchResult` ordered by relevance/score
            descending.

        Raises:
            ValueError: If ``mode`` is invalid or ``"semantic"`` is requested
                without a configured embedder.
        """
        if mode not in {"fts", "semantic", "auto"}:
            raise ValueError(
                f"Invalid mode {mode!r}; expected fts|semantic|auto"
            )

        if mode == "semantic":
            if self._embedder is None:
                raise ValueError(
                    "Semantic search requires an embedder. Pass embedder=... "
                    "to MessageSearch() or use mode='fts'."
                )
            return self._search_semantic(query, session_id, limit)

        if mode == "auto":
            if self._embedder is not None:
                return self._search_semantic(query, session_id, limit)
            return self._search_fts(query, session_id, limit)

        return self._search_fts(query, session_id, limit)

    def index_session(self, session_id: str) -> int:
        """Compute and store embeddings for all unindexed messages in a session.

        Returns:
            The number of messages that were embedded and stored.

        Raises:
            RuntimeError: If no embedder is configured.
        """
        if self._embedder is None or self._embedding_dim is None:
            raise RuntimeError(
                "No embedder configured — cannot compute embeddings."
            )
        if not _NP_AVAILABLE:
            raise ImportError(
                "numpy is required for semantic indexing. Install it: pip install numpy"
            )

        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row

        rows = conn.execute(
            "SELECT id, content FROM messages "
            "WHERE session_id = ? AND content IS NOT NULL AND content != '' "
            "AND id NOT IN (SELECT message_id FROM message_embeddings)",
            (session_id,),
        ).fetchall()

        if not rows:
            conn.close()
            return 0

        params: list[tuple[int, bytes]] = []
        for row in rows:
            text: str = row["content"]
            vec = self._embedder(text)
            if len(vec) != self._embedding_dim:
                raise ValueError(
                    f"Embedder returned {len(vec)}-D vector; "
                    f"expected {self._embedding_dim}D."
                )
            emb_bytes = np.array(vec, dtype=np.float32).tobytes()  # type: ignore[union-attr]
            params.append((row["id"], emb_bytes))

        conn.executemany(
            "INSERT OR REPLACE INTO message_embeddings (message_id, embedding) "
            "VALUES (?, ?)",
            params,
        )
        conn.commit()
        conn.close()
        return len(params)

    def _ensure_embedding_schema(self) -> None:
        if self._embedding_dim is None:
            return
        conn = sqlite3.connect(str(self.db_path))
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS message_embeddings (
                message_id INTEGER PRIMARY KEY,
                embedding BLOB NOT NULL,
                FOREIGN KEY (message_id) REFERENCES messages(id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_message_embeddings_message_id "
            "ON message_embeddings(message_id)"
        )
        conn.commit()
        conn.close()

    def _search_fts(
        self,
        query: str,
        session_id: str | None,
        limit: int,
    ) -> list[SearchResult]:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row

        if session_id:
            rows = conn.execute(
                "SELECT m.id, m.session_id, m.role, m.content, m.created_at, "
                "bm25(messages_fts) AS score "
                "FROM messages m "
                "JOIN messages_fts f ON m.id = f.rowid "
                "WHERE m.session_id = ? AND messages_fts MATCH ? "
                "ORDER BY score LIMIT ?",
                (session_id, query, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT m.id, m.session_id, m.role, m.content, m.created_at, "
                "bm25(messages_fts) AS score "
                "FROM messages m "
                "JOIN messages_fts f ON m.id = f.rowid "
                "WHERE messages_fts MATCH ? "
                "ORDER BY score LIMIT ?",
                (query, limit),
            ).fetchall()

        conn.close()
        return [
            SearchResult(
                message_id=row["id"],
                session_id=row["session_id"],
                role=row["role"],
                content=row["content"],
                score=row["score"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def _search_semantic(
        self,
        query: str,
        session_id: str | None,
        limit: int,
    ) -> list[SearchResult]:
        if self._embedder is None or not _NP_AVAILABLE:
            return []

        query_vec = np.array(self._embedder(query), dtype=np.float32)  # type: ignore[union-attr]
        query_norm = np.linalg.norm(query_vec)  # type: ignore[union-attr]
        if query_norm == 0:
            return []

        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row

        if session_id:
            rows = conn.execute(
                "SELECT e.message_id, e.embedding, m.session_id, m.role, "
                "m.content, m.created_at "
                "FROM message_embeddings e "
                "JOIN messages m ON e.message_id = m.id "
                "WHERE m.session_id = ?",
                (session_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT e.message_id, e.embedding, m.session_id, m.role, "
                "m.content, m.created_at "
                "FROM message_embeddings e "
                "JOIN messages m ON e.message_id = m.id"
            ).fetchall()

        results: list[SearchResult] = []
        for row in rows:
            emb = np.frombuffer(bytes(row["embedding"]), dtype=np.float32)  # type: ignore[union-attr]
            cos_sim = float(
                np.dot(emb, query_vec)  # type: ignore[union-attr]
                / (np.linalg.norm(emb) * query_norm)  # type: ignore[union-attr]
            )
            results.append(
                SearchResult(
                    message_id=row["message_id"],
                    session_id=row["session_id"],
                    role=row["role"],
                    content=row["content"],
                    score=cos_sim,
                    created_at=row["created_at"],
                )
            )

        conn.close()
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]
