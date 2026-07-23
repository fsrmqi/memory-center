"""低风险、显式触发的工作区存储维护。"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .workspace import WorkspaceStore


def cleanup_legacy_memory_store(workspace_file: str | Path, *, apply: bool = False) -> dict[str, Any]:
    """Remove the retired `memory/memory.db` only when it is not the runtime DB."""
    store = WorkspaceStore(workspace_file)
    legacy = store.memory_dir / "memory.db"
    runtime = store.runtime_db_path.resolve()
    candidate = legacy.exists() and legacy.resolve() != runtime
    payload: dict[str, Any] = {
        "runtime_db": str(runtime),
        "candidate": str(legacy) if candidate else "",
        "bytes": legacy.stat().st_size if candidate else 0,
        "apply": apply,
        "removed": [],
        "next_action": "运行 storage-legacy-cleanup --apply 删除未使用的旧存储副本。" if candidate and not apply else "当前没有可清理的旧 memory.db。",
    }
    if not candidate or not apply:
        return payload
    for suffix in ("", "-wal", "-shm", "-journal"):
        path = Path(f"{legacy}{suffix}")
        if path.exists():
            size = path.stat().st_size
            path.unlink()
            payload["removed"].append({"path": str(path), "bytes": size})
    payload["next_action"] = "旧存储副本已删除；当前运行时继续使用 graph/graph.db。"
    return payload


def sparsify_static_assertions(workspace_file: str | Path, *, apply: bool = False) -> dict[str, Any]:
    """Delete materialized EXTRACTED rows; graph edges become the static source."""
    store = WorkspaceStore(workspace_file)
    with store.memory_backend().connect() as conn:
        extracted = int(conn.execute("SELECT COUNT(*) FROM assertions WHERE status='EXTRACTED'").fetchone()[0])
    export = store.memory_dir / "assertions.jsonl"
    payload: dict[str, Any] = {"extracted_rows": extracted, "export_bytes": export.stat().st_size if export.exists() else 0, "apply": apply, "deleted_rows": 0, "next_action": "运行 assertion-sparsify --apply 删除旧静态断言副本；随后按需执行 assertion-vacuum 回收 SQLite 页。"}
    if not apply:
        return payload
    with store.memory_backend().connect() as conn:
        payload["deleted_rows"] = int(conn.execute("DELETE FROM assertions WHERE status='EXTRACTED'").rowcount)
    export.write_text(json.dumps({"schema_version": 2, "mode": "derived_static_assertions", "note": "静态断言从 graph edges 按需派生；本文件不再保存全量副本。"}, ensure_ascii=False) + "\n", encoding="utf-8")
    payload["next_action"] = "已删除静态副本；运行 assertion-vacuum 可回收 SQLite 文件空间。"
    return payload


def vacuum_runtime_store(workspace_file: str | Path, *, apply: bool = False) -> dict[str, Any]:
    """Explicitly reclaim SQLite pages after a large offline cleanup."""
    store = WorkspaceStore(workspace_file)
    path = store.runtime_db_path
    before = path.stat().st_size if path.exists() else 0
    payload: dict[str, Any] = {"db": str(path), "before_bytes": before, "apply": apply, "after_bytes": before, "next_action": "确认无重建任务后运行 assertion-vacuum --apply；该操作会短暂独占 SQLite。"}
    if not apply:
        return payload
    with sqlite3.connect(path, timeout=30) as conn:
        conn.execute("VACUUM")
    payload["after_bytes"] = path.stat().st_size if path.exists() else 0
    payload["next_action"] = "SQLite 页已重整回收。"
    return payload
