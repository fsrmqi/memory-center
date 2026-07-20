"""Tests for memory_center.core.storage.pragmas.

Covers:
- ``apply_pragmas`` flips a fresh connection to the documented defaults
  (WAL, NORMAL, 200 MB cache, MEMORY temp_store, 256 MB mmap, FK on).
- ``read_pragma_state`` reports the values back in human-readable form
  (synchronous/temp_store names instead of integers).
- ``fast_write_mode`` temporarily flips ``synchronous`` to OFF and
  restores the prior value even when the body raises.
- RuntimeStore 的图、运行记录与向量访问共享同一套 PRAGMA 配置。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from memory_center.core.storage.pragmas import (
    FAST_WRITE_PROFILE,
    apply_pragmas,
    fast_write_mode,
    read_pragma_state,
)


def _open(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


# ── apply_pragmas / read_pragma_state ──────────────────────────────────────


def test_apply_pragmas_sets_documented_defaults(tmp_path: Path) -> None:
    conn = _open(tmp_path / "x.sqlite")
    apply_pragmas(conn)
    state = read_pragma_state(conn)

    assert str(state["journal_mode"]).lower() == "wal"
    assert state["synchronous"] == "NORMAL"
    # cache_size is reported as the negative KiB we set.
    assert int(state["cache_size"]) == -200_000
    assert state["temp_store"] == "MEMORY"
    assert int(state["mmap_size"]) == 256 * 1024 * 1024
    assert state["foreign_keys"] == "ON"


def test_apply_pragmas_idempotent(tmp_path: Path) -> None:
    conn = _open(tmp_path / "x.sqlite")
    apply_pragmas(conn)
    apply_pragmas(conn)
    state = read_pragma_state(conn)
    assert state["synchronous"] == "NORMAL"


# ── fast_write_mode ────────────────────────────────────────────────────────


def test_fast_write_mode_flips_synchronous_off(tmp_path: Path) -> None:
    conn = _open(tmp_path / "x.sqlite")
    apply_pragmas(conn)
    assert read_pragma_state(conn)["synchronous"] == "NORMAL"

    with fast_write_mode(conn):
        assert read_pragma_state(conn)["synchronous"] == "OFF"
        # Other PRAGMAs are untouched.
        assert read_pragma_state(conn)["temp_store"] == "MEMORY"

    # Restored on exit.
    assert read_pragma_state(conn)["synchronous"] == "NORMAL"


def test_fast_write_mode_restores_on_exception(tmp_path: Path) -> None:
    conn = _open(tmp_path / "x.sqlite")
    apply_pragmas(conn)

    with pytest.raises(RuntimeError, match="boom"):
        with fast_write_mode(conn):
            assert read_pragma_state(conn)["synchronous"] == "OFF"
            raise RuntimeError("boom")

    # Even though the body raised, the PRAGMA was restored.
    assert read_pragma_state(conn)["synchronous"] == "NORMAL"


# ── Store integration: RuntimeStore 统一继承 PRAGMA ─────────────────────────


def test_graph_store_connect_applies_pragmas(tmp_path: Path) -> None:
    from memory_center.core.storage.runtime import RuntimeStore

    with RuntimeStore(tmp_path / "graph.sqlite") as graph:
        state = read_pragma_state(graph.connect())
    assert str(state["journal_mode"]).lower() == "wal"
    assert state["synchronous"] == "NORMAL"
    assert state["temp_store"] == "MEMORY"
    assert int(state["cache_size"]) == -200_000


def test_runtime_record_store_connect_applies_pragmas(tmp_path: Path) -> None:
    from memory_center.core.storage.runtime import RuntimeStore

    with RuntimeStore(tmp_path / "mem.sqlite") as mem:
        state = read_pragma_state(mem.connect())
    assert str(state["journal_mode"]).lower() == "wal"
    assert state["synchronous"] == "NORMAL"


def test_unified_store_pool_applies_pragmas(tmp_path: Path) -> None:
    from memory_center.core.storage.runtime import RuntimeStore

    store = RuntimeStore(tmp_path / "unified.sqlite", pool_size=1)
    try:
        with store.pool.connection() as conn:
            state = read_pragma_state(conn)
        assert str(state["journal_mode"]).lower() == "wal"
        assert state["temp_store"] == "MEMORY"
        assert int(state["cache_size"]) == -200_000
    finally:
        store.pool.close()


# ── FAST_WRITE_PROFILE shape ──────────────────────────────────────────────


def test_fast_write_profile_keeps_default_cache_and_mmap() -> None:
    """The fast write profile should only differ from default in
    ``synchronous``; flipping cache/mmap/temp_store back and forth is
    pure overhead during reindex."""
    assert FAST_WRITE_PROFILE.synchronous == "OFF"
    assert FAST_WRITE_PROFILE.cache_size_kb == 200_000
    assert FAST_WRITE_PROFILE.temp_store == "MEMORY"
    assert FAST_WRITE_PROFILE.mmap_size_bytes == 256 * 1024 * 1024
