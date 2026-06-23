"""SQLite connection pool with WAL mode.

Provides thread-safe connection reuse so callers don't open/close SQLite
connections on every function call — the main performance bottleneck in 2.x.
"""
from __future__ import annotations

import queue
import sqlite3
import threading
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .pragmas import apply_pragmas


class SQLitePool:
    """Simple connection pool for a single SQLite database.

    Usage::

        pool = SQLitePool("/path/to/db.sqlite3")
        with pool.connection() as conn:
            conn.execute("SELECT 1")
        pool.close()
    """

    def __init__(self, db_path: str | Path, pool_size: int = 4):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._pool: queue.SimpleQueue[sqlite3.Connection] = queue.SimpleQueue()
        self._lock = threading.Lock()
        self._closed = False
        for _ in range(pool_size):
            self._pool.put(self._new_connection())

    def _new_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        apply_pragmas(conn)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Get a pooled connection. Returns it automatically on exit."""
        conn = self._pool.get()
        try:
            yield conn
        finally:
            if not self._closed:
                self._pool.put(conn)

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """Get a pooled connection inside a transaction (auto-commit/rollback)."""
        with self.connection() as conn:
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def close(self) -> None:
        """Close all pooled connections."""
        self._closed = True
        while not self._pool.empty():
            try:
                conn = self._pool.get_nowait()
                conn.close()
            except Exception:
                pass

    def __enter__(self) -> SQLitePool:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
