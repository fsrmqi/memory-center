"""Shared SQLite tuning helpers.

Single source of truth for the PRAGMA values memory-center applies to every
SQLite connection it owns. Multiple stores (``GraphStore``,
``MemoryBackendStore``, ``UnifiedStore`` via ``SQLitePool``) historically
configured PRAGMAs independently, with at least one of them not configuring
them at all — that hidden inconsistency was a major reindex bottleneck.

This module keeps the configuration declarative so every store applies the
same defaults, and so we can ship one ``fast_write_mode`` context manager
that is safe to use across stores during heavy bulk writes (reindex).

The PRAGMA values are tuned for memory-center's workload:

- ``journal_mode=WAL`` — readers don't block writers and vice versa.
- ``synchronous=NORMAL`` — safe with WAL; full ``FULL`` is overkill for an
  index that can always be rebuilt from source code.
- ``cache_size=-200000`` — 200 MB page cache. The original 64 MB defaulted
  to disk hits on mid-size monorepos.
- ``temp_store=MEMORY`` — sort/temp tables in RAM instead of /tmp.
- ``mmap_size=268435456`` — 256 MB memory-mapped I/O window for read-heavy
  query paths.
- ``foreign_keys=ON`` — enforced everywhere even though we don't currently
  rely on FK constraints; this catches accidental dangling-edge bugs early.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass(frozen=True)
class PragmaProfile:
    """Named bundle of PRAGMA settings.

    ``DEFAULT`` is what every connection gets on open. ``FAST_WRITE`` is
    applied temporarily during full reindex via ``fast_write_mode``.
    """

    journal_mode: str = "WAL"
    synchronous: str = "NORMAL"
    cache_size_kb: int = 200_000           # 200 MB (negative value → KiB)
    temp_store: str = "MEMORY"
    mmap_size_bytes: int = 256 * 1024 * 1024
    foreign_keys: bool = True


DEFAULT_PROFILE = PragmaProfile()
"""Profile applied to every connection on creation."""

FAST_WRITE_PROFILE = PragmaProfile(
    journal_mode="WAL",
    # ``synchronous=OFF`` is safe ONLY for full reindex: if the process
    # crashes mid-reindex we re-derive the graph from source code anyway.
    # Incremental updates must NOT use this — keep ``DEFAULT_PROFILE``
    # there to survive a crash without losing recent edits.
    synchronous="OFF",
    cache_size_kb=200_000,
    temp_store="MEMORY",
    mmap_size_bytes=256 * 1024 * 1024,
    foreign_keys=True,
)


def apply_pragmas(conn: sqlite3.Connection, profile: PragmaProfile = DEFAULT_PROFILE) -> None:
    """Configure ``conn`` according to ``profile``.

    Safe to call multiple times on the same connection — PRAGMAs are
    idempotent. WAL upgrade is best-effort: some SQLite builds (e.g.
    in-memory databases or :memory: shared cache) ignore the request,
    which we treat as non-fatal.
    """
    conn.execute(f"PRAGMA journal_mode={profile.journal_mode}")
    conn.execute(f"PRAGMA synchronous={profile.synchronous}")
    # ``cache_size`` accepts a negative number to mean KiB regardless of
    # page size; that's exactly what we want here.
    conn.execute(f"PRAGMA cache_size=-{profile.cache_size_kb}")
    conn.execute(f"PRAGMA temp_store={profile.temp_store}")
    conn.execute(f"PRAGMA mmap_size={profile.mmap_size_bytes}")
    conn.execute(f"PRAGMA foreign_keys={'ON' if profile.foreign_keys else 'OFF'}")


def read_pragma_state(conn: sqlite3.Connection) -> dict[str, str | int]:
    """Return the current PRAGMA values for diagnostics (``memory-center
    doctor`` surfaces this to users)."""
    state: dict[str, str | int] = {}
    for key in (
        "journal_mode",
        "synchronous",
        "cache_size",
        "temp_store",
        "mmap_size",
        "foreign_keys",
    ):
        row = conn.execute(f"PRAGMA {key}").fetchone()
        if row is None:
            continue
        value = row[0]
        # ``synchronous`` is reported as 0/1/2/3 internally; map back to
        # the names we configured so the diagnostic output is readable.
        if key == "synchronous":
            value = {0: "OFF", 1: "NORMAL", 2: "FULL", 3: "EXTRA"}.get(int(value), value)
        if key == "temp_store":
            value = {0: "DEFAULT", 1: "FILE", 2: "MEMORY"}.get(int(value), value)
        if key == "foreign_keys":
            value = "ON" if int(value) == 1 else "OFF"
        state[key] = value
    return state


@contextmanager
def fast_write_mode(conn: sqlite3.Connection) -> Generator[None, None, None]:
    """Temporarily switch ``conn`` to ``FAST_WRITE_PROFILE`` for bulk writes.

    Only safe inside a full reindex (or other workloads that can recover
    from a crash by re-running the same job). Incremental updates and any
    user-data writes must stay on ``DEFAULT_PROFILE``.

    Restores the previous ``synchronous`` value on exit even if the bulk
    write raises. Other PRAGMAs are not touched because the default values
    are already ``MEMORY``/large/WAL, and flipping them back and forth
    only buys overhead.
    """
    prev_row = conn.execute("PRAGMA synchronous").fetchone()
    prev_value = int(prev_row[0]) if prev_row is not None else 1  # NORMAL
    conn.execute(f"PRAGMA synchronous={FAST_WRITE_PROFILE.synchronous}")
    try:
        yield
    finally:
        # Map the integer back to a name so the PRAGMA statement is valid.
        restore = {0: "OFF", 1: "NORMAL", 2: "FULL", 3: "EXTRA"}.get(prev_value, "NORMAL")
        conn.execute(f"PRAGMA synchronous={restore}")
