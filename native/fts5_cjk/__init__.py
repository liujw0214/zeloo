"""FTS5 Chinese tokenization bridge.

SQLite FTS5 doesn't support CJK segmentation out of the box. This
module provides a Python-side tokenizer that can be used as a
fallback when the native Rust extension (``native/fts5_cjk``) is not
available.

Strategy:

* If the optional ``jieba`` package is installed, use it for proper
  Chinese word segmentation.
* Otherwise fall back to character-by-character tokenization.
* Provides :func:`tokenize_cjk` (callable from SQL via SQLite user
  functions) and :func:`create_fts5_table` to create an FTS5 virtual
  table wired with the tokenizer.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterable

logger = logging.getLogger(__name__)

_JIEBA: object | None = None
_JIEBA_AVAILABLE = False


def _try_import_jieba() -> None:
    """Try to import jieba once, caching the result."""
    global _JIEBA, _JIEBA_AVAILABLE
    if _JIEBA is not None:
        return
    try:
        import jieba  # type: ignore[import-untyped]

        _JIEBA = jieba
        _JIEBA_AVAILABLE = True
        jieba.setLogLevel(logging.WARNING)
    except ImportError:
        _JIEBA = None
        _JIEBA_AVAILABLE = False


def tokenize_cjk(text: str) -> str:
    """Tokenize *text* and return space-separated tokens.

    Uses jieba if available, otherwise falls back to per-character
    splitting.
    """
    _try_import_jieba()
    if _JIEBA_AVAILABLE and _JIEBA is not None:
        try:
            tokens = list(_JIEBA.cut(text, cut_all=False))  # type: ignore[attr-defined]
            return " ".join(tokens)
        except Exception as exc:
            logger.warning("jieba tokenization failed: %s — falling back to chars", exc)

    # Character-level fallback: emit each Han char + ASCII word separately.
    return " ".join(_char_tokenize(text))


def _char_tokenize(text: str) -> Iterable[str]:
    """Yield per-character tokens for CJK + per-word tokens for ASCII."""
    buf: list[str] = []
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff" or "\u3040" <= ch <= "\u30ff":
            if buf:
                yield "".join(buf)
                buf.clear()
            yield ch
        elif ch.isalnum():
            buf.append(ch)
        else:
            if buf:
                yield "".join(buf)
                buf.clear()
    if buf:
        yield "".join(buf)


def register_tokenizer(conn: sqlite3.Connection) -> None:
    """Register ``tokenize_cjk`` as a SQLite scalar function.

    After registration, FTS5 virtual tables can use the tokenizer via::

        CREATE VIRTUAL TABLE messages_fts USING fts5(
            content,
            tokenize='unicode61 remove_diacritics 2'
        )

    Note: SQLite's FTS5 doesn't accept user-defined Python functions as
    tokenizers directly; this function registers a scalar helper
    :func:`cjk_tokenize` that can be invoked from SQL triggers or used
    from Python to pre-tokenize text before insertion.
    """
    conn.create_function("cjk_tokenize", 1, tokenize_cjk, deterministic=True)


def create_fts5_table(
    conn: sqlite3.Connection,
    table_name: str,
    columns: list[str],
    use_external_content: tuple[str, list[str]] | None = None,
) -> None:
    """Create an FTS5 virtual table *table_name* with the CJK tokenizer.

    Args:
        conn: An open SQLite connection.
        table_name: Name for the FTS5 virtual table (e.g. ``messages_fts``).
        columns: Columns to index (e.g. ``["content", "title"]``).
        use_external_content: Optional ``(table, cols)`` for FTS5's
            external-content mode — saves space by indexing an existing
            table without duplicating data.
    """
    cols = ", ".join(columns)
    if use_external_content:
        src_table, src_cols = use_external_content
        sql = (
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {table_name} USING fts5("
            f"{cols}, content='{src_table}', content_rowid='id')"
        )
    else:
        sql = f"CREATE VIRTUAL TABLE IF NOT EXISTS {table_name} USING fts5({cols})"

    conn.execute(sql)
    register_tokenizer(conn)
    logger.info("Created FTS5 virtual table %s with CJK tokenizer", table_name)


def is_jieba_available() -> bool:
    """Return True if jieba is installed and usable."""
    _try_import_jieba()
    return _JIEBA_AVAILABLE