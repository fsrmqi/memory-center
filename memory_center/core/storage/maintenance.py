"""低风险、显式触发的工作区存储维护。"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .workspace import WorkspaceStore


def compact_semantic_runtime_state(workspace_file: str | Path, *, apply: bool = False) -> dict[str, Any]:
    """Remove the retired semantic document mirror without rebuilding the graph."""
    from memory_center.core.retrieval.semantic import SEMANTIC_INDEX_FILE, SEMANTIC_INDEX_VERSION

    store = WorkspaceStore(workspace_file)
    payload = store.read_json_prefer_backend(SEMANTIC_INDEX_FILE, {}) or {}
    removable = {key: payload[key] for key in ("docs", "df", "avgdl") if key in payload}
    before_bytes = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    compacted = {key: value for key, value in payload.items() if key not in removable}
    compacted["version"] = SEMANTIC_INDEX_VERSION
    compacted["storage_mode"] = "runtime_indexes_v1"
    after_bytes = len(json.dumps(compacted, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    result: dict[str, Any] = {
        "apply": apply,
        "semantic_metadata_bytes_before": before_bytes,
        "semantic_metadata_bytes_after": after_bytes,
        "estimated_reclaimable_bytes": max(0, before_bytes - after_bytes),
        "removed_fields": sorted(removable),
        "changed": bool(removable),
        "next_action": "运行 artifact semantic-index-compact --apply；随后在无写入任务时运行 artifact storage-vacuum --apply 回收 SQLite 页。" if removable and not apply else "语义状态已精简；运行 artifact storage-vacuum --apply 回收 SQLite 页。",
    }
    if apply and removable:
        store.write_json(SEMANTIC_INDEX_FILE, compacted)
    return result


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
    """Delete every legacy static assertion mirror; graph edges remain the source."""
    store = WorkspaceStore(workspace_file)
    with store.memory_backend().connect() as conn:
        assertion_rows = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM assertions
                WHERE provenance_kind='STATIC' AND relation_mode='STRUCTURAL'
                """
            ).fetchone()[0]
        )
        json_rows = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM json_records
                WHERE collection='assertions.jsonl' AND type='static_assertion'
                """
            ).fetchone()[0]
        )
    export = store.memory_dir / "assertions.jsonl"
    payload: dict[str, Any] = {
        "static_assertion_rows": assertion_rows,
        "static_json_rows": json_rows,
        "export_bytes": export.stat().st_size if export.exists() else 0,
        "apply": apply,
        "deleted_assertion_rows": 0,
        "deleted_json_rows": 0,
        "next_action": "运行 assertion-sparsify --apply 删除旧静态断言镜像；随后按需执行 assertion-vacuum 回收 SQLite 页。",
    }
    if not apply:
        return payload
    with store.memory_backend().connect() as conn:
        payload["deleted_assertion_rows"] = int(
            conn.execute(
                """
                DELETE FROM assertions
                WHERE provenance_kind='STATIC' AND relation_mode='STRUCTURAL'
                """
            ).rowcount
        )
        payload["deleted_json_rows"] = int(
            conn.execute(
                """
                DELETE FROM json_records
                WHERE collection='assertions.jsonl' AND type='static_assertion'
                """
            ).rowcount
        )
    export.write_text(json.dumps({"schema_version": 2, "mode": "derived_static_assertions", "note": "静态断言从 graph edges 按需派生；本文件不再保存全量副本。"}, ensure_ascii=False) + "\n", encoding="utf-8")
    payload["next_action"] = "已删除静态副本；运行 assertion-vacuum 可回收 SQLite 文件空间。"
    return payload


def vacuum_runtime_store(workspace_file: str | Path, *, apply: bool = False) -> dict[str, Any]:
    """Explicitly reclaim SQLite pages after a large offline cleanup."""
    store = WorkspaceStore(workspace_file)
    path = store.runtime_db_path
    before = path.stat().st_size if path.exists() else 0
    payload: dict[str, Any] = {"db": str(path), "before_bytes": before, "apply": apply, "after_bytes": before, "next_action": "确认无重建任务后运行 storage-vacuum --apply；该操作会短暂独占 SQLite。"}
    if not apply:
        return payload
    with sqlite3.connect(path, timeout=30) as conn:
        conn.execute("VACUUM")
    payload["after_bytes"] = path.stat().st_size if path.exists() else 0
    payload["next_action"] = "SQLite 页已重整回收。"
    return payload
