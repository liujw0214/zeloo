"""Connection pool for SQLite databases.

Manages a fixed pool of :class:`sqlite3.Connection` objects so that
concurrent read operations don't all compete for a single connection.
Write operations are still serialized via the application-level
:class:`RWLock` (see :mod:`zeloo_state.guard`).

Usage::

    pool = ConnectionPool(db_path, pool_size=5)
    with pool.get_connection() as conn:
        conn.execute("SELECT ...")
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from zeloo_state.guard import RWLock

logger = logging.getLogger(__name__)

_DEFAULT_POOL_SIZE = 5


class ConnectionPool:
    """A bounded pool of SQLite connections.

    Connections are created lazily up to *pool_size*. Acquiring a
    connection when the pool is empty blocks until one is returned or
    times out.

    Args:
        db_path: Path to the SQLite database file.
        pool_size: Maximum number of pooled connections.
        timeout: Seconds to wait for a connection before raising.
        wal: Enable WAL journal mode (default True — recommended
            for concurrent access).
    """

    def __init__(
        self,
        db_path: str | Path,
        pool_size: int = _DEFAULT_POOL_SIZE,
        timeout: float = 30.0,
        wal: bool = True,
    ) -> None:
        self.db_path = str(db_path)
        self.pool_size = max(1, pool_size)
        self.timeout = timeout
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._available: list[sqlite3.Connection] = []
        self._total = 0
        self._closed = False
        self._rwlock = RWLock()

        if wal:
            self._enable_wal()

    def _enable_wal(self) -> None:
        """Open a temporary connection to enable WAL journal mode."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.close()
        except Exception as exc:
            logger.warning("Failed to enable WAL mode: %s", exc)

    def _create_connection(self) -> sqlite3.Connection:
        """Create a new SQLite connection with sensible defaults."""
        conn = sqlite3.connect(
            self.db_path,
            timeout=self.timeout,
            check_same_thread=False,
        )
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        self._total += 1
        return conn

    @contextmanager
    def get_connection(self) -> Iterator[sqlite3.Connection]:
        """Acquire a connection from the pool.

        Yields a connection and returns it to the pool on exit. If the
        pool is exhausted and at capacity, blocks until one is free.
        """
        if self._closed:
            raise RuntimeError("ConnectionPool is closed")

        with self._cond:
            while not self._available:
                if self._total < self.pool_size:
                    conn = self._create_connection()
                    break
                # Pool exhausted — wait for a returned connection.
                if not self._cond.wait(timeout=self.timeout):
                    raise TimeoutError(
                        f"Timed out waiting for a database connection "
                        f"after {self.timeout}s"
                    )
            else:
                conn = self._available.pop()

        try:
            yield conn
        except Exception:
            # Don't return potentially-tainted connections; recreate.
            try:
                conn.close()
            except Exception:
                pass
            with self._cond:
                self._total -= 1
                self._cond.notify()
            raise
        else:
            with self._cond:
                if self._closed:
                    conn.close()
                    self._total -= 1
                else:
                    self._available.append(conn)
                    self._cond.notify()

    @contextmanager
    def write_transaction(self) -> Iterator[sqlite3.Connection]:
        """Acquire an exclusive write connection.

        Holds the write lock for the duration, serializing writes.
        """
        with self._rwlock.write_lock():
            with self.get_connection() as conn:
                try:
                    yield conn
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise

    def close(self) -> None:
        """Close all pooled connections."""
        with self._cond:
            self._closed = True
            for conn in self._available:
                try:
                    conn.close()
                except Exception:
                    pass
            self._available.clear()
            self._total = 0
            self._cond.notify_all()
        logger.info("ConnectionPool closed (was %d connections)", self._total)

    def __enter__(self) -> ConnectionPool:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
