"""Reader-Writer lock for concurrent database access.

Provides :class:`RWLock` with writer-preference semantics: multiple
readers may hold the lock simultaneously, but only one writer, and
writers are not starved by a continuous stream of readers.

Usage::

    lock = RWLock()
    with lock.read_lock():
        # safe to read concurrently
        ...
    with lock.write_lock():
        # exclusive write access
        ...
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager


class RWLock:
    """Reader-Writer lock with writer preference.

    Multiple readers can acquire the lock concurrently. Writers get
    exclusive access. When a writer is waiting, new readers block until
    the writer completes — this prevents writer starvation.
    """

    def __init__(self) -> None:
        self._read_ready = threading.Condition(threading.Lock())
        self._readers = 0
        self._writers_waiting = 0
        self._writer_active = False

    @contextmanager
    def read_lock(self) -> Iterator[None]:
        """Acquire a shared read lock.

        Blocks if a writer holds the lock or is waiting.
        """
        with self._read_ready:
            while self._writer_active or self._writers_waiting > 0:
                self._read_ready.wait()
            self._readers += 1
        try:
            yield
        finally:
            with self._read_ready:
                self._readers -= 1
                if self._readers == 0:
                    self._read_ready.notify_all()

    @contextmanager
    def write_lock(self) -> Iterator[None]:
        """Acquire an exclusive write lock.

        Blocks until all readers release and no other writer holds the
        lock. New readers are blocked while this writer waits.
        """
        with self._read_ready:
            self._writers_waiting += 1
            while self._writer_active or self._readers > 0:
                self._read_ready.wait()
            self._writers_waiting -= 1
            self._writer_active = True
        try:
            yield
        finally:
            with self._read_ready:
                self._writer_active = False
                self._read_ready.notify_all()

    @property
    def reader_count(self) -> int:
        """Current number of active readers (for diagnostics)."""
        return self._readers

    @property
    def writer_active(self) -> bool:
        """True while a writer holds the lock."""
        return self._writer_active
