"""低风险、显式触发的工作区存储维护。"""
from __future__ import annotations

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
