"""会话派生状态仓储：所有运行时 bookkeeping 经 SQLite 权威库读写。"""
from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from filelock import FileLock

from .workspace import WorkspaceStore

SERVED_FILES_STATE = "served_files_v1"
MAX_SERVED_PATHS = 500
MAX_SERVED_SESSIONS = 50


class SessionStateRepository:
    """会话级派生状态的唯一存储边界；失败由调用方按无状态降级。"""

    def __init__(self, workspace_file: str | Path):
        self.store = WorkspaceStore(workspace_file)

    def served_files(self, session_id: str) -> set[str]:
        payload = self.store.memory_backend().get_session_state(SERVED_FILES_STATE, session_id.strip())
        paths = payload.get("paths", []) if isinstance(payload, dict) else []
        return {str(path) for path in paths if isinstance(path, str) and path}

    def record_served_files(self, session_id: str, paths: Iterable[str], *, tier: str = "") -> int:
        sid = session_id.strip()
        normalized = [str(path).replace("\\", "/").strip() for path in paths]
        normalized = [path for path in normalized if path]
        if not sid:
            return 0
        with FileLock(str(self.store.audit_lock_file)):
            current = self.store.memory_backend().get_session_state(SERVED_FILES_STATE, sid) or {}
            ordered = OrderedDict((str(path), None) for path in current.get("paths", []) if isinstance(path, str) and path)
            for path in normalized:
                ordered.pop(path, None)
                ordered[path] = None
            while len(ordered) > MAX_SERVED_PATHS:
                ordered.popitem(last=False)
            self.store.memory_backend().upsert_session_state(
                SERVED_FILES_STATE,
                sid,
                {"paths": list(ordered), "tier": str(tier or "")},
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
            self.store.memory_backend().prune_session_states(SERVED_FILES_STATE, max_sessions=MAX_SERVED_SESSIONS)
            return len(ordered)


__all__ = ["SessionStateRepository", "SERVED_FILES_STATE", "MAX_SERVED_PATHS", "MAX_SERVED_SESSIONS"]
