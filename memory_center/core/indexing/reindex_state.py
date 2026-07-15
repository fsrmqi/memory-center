"""Workspace-level coordination and status for long-running reindex jobs."""
from __future__ import annotations

import os
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from filelock import FileLock, Timeout

from ..diagnostics import safe_reason
from ..errors import ConflictError
from ..store import WorkspaceStore

REINDEX_STATE_FILE = "reindex-state.json"


class ReindexBusyError(ConflictError):
    """Raised when another supported Memory Center reindex owns the workspace."""

    def __init__(self, state: dict[str, Any], timeout_seconds: float) -> None:
        diagnostics = {
            "status": state.get("status", "unknown"),
            "started_at": state.get("started_at", ""),
            "operation_id": state.get("operation_id", ""),
            "timeout_seconds": timeout_seconds,
        }
        super().__init__(
            "A workspace reindex is already running.",
            diagnostics=diagnostics,
            suggested_action="Wait for the current reindex to finish, or retry with --lock-timeout <seconds>.",
        )


def workspace_reindex_status(store: WorkspaceStore) -> dict[str, Any]:
    """Return a path-free reindex lifecycle snapshot for status surfaces."""
    state = store.read_json(REINDEX_STATE_FILE, {})
    if not isinstance(state, dict) or not state:
        return {
            "status": "idle",
            "lock_held": False,
            "recommended_action": "Run reindex when indexed evidence is stale.",
        }

    lock_held = _lock_held(store)
    result = {
        "schema_version": 1,
        "status": str(state.get("status", "unknown") or "unknown"),
        "lock_held": lock_held,
        "operation_id": str(state.get("operation_id", "") or ""),
        "started_at": str(state.get("started_at", "") or ""),
        "completed_at": str(state.get("completed_at", "") or ""),
        "duration_seconds": state.get("duration_seconds"),
        "mode": str(state.get("mode", "") or ""),
        "project_count": int(state.get("project_count", 0) or 0),
        "path_count": int(state.get("path_count", 0) or 0),
        "last_success_at": str(state.get("last_success_at", "") or ""),
        "error": str(state.get("error", "") or ""),
    }
    if result["status"] == "running" and not lock_held:
        result["status"] = "interrupted"
        result["recommended_action"] = "The previous reindex no longer owns the lock; retry reindex."
    elif result["status"] == "running":
        result["recommended_action"] = "Wait for the active reindex to finish before starting another one."
    elif result["status"] == "succeeded":
        result["recommended_action"] = "Use current index evidence."
    else:
        result["recommended_action"] = "Retry reindex after resolving the reported failure."
    return result


@contextmanager
def workspace_reindex_lock(
    store: WorkspaceStore,
    *,
    projects: Sequence[str] | None = None,
    paths: Sequence[str] | None = None,
    timeout_seconds: float = 0.0,
) -> Iterator[None]:
    """Serialize reindex writers and record a recoverable lifecycle state."""
    timeout = max(0.0, float(timeout_seconds or 0.0))
    lock = FileLock(str(store.reindex_lock_file))
    try:
        lock.acquire(timeout=timeout)
    except Timeout as exc:
        raise ReindexBusyError(workspace_reindex_status(store), timeout) from exc

    started_at = _utc_now()
    started_monotonic = time.monotonic()
    previous = store.read_json(REINDEX_STATE_FILE, {})
    previous_success = _last_success_at(previous)
    state = {
        "schema_version": 1,
        "status": "running",
        "operation_id": uuid4().hex,
        "pid": os.getpid(),
        "started_at": started_at,
        "mode": "partial" if projects or paths else "full",
        "project_count": len(projects or []),
        "path_count": len(paths or []),
        "last_success_at": previous_success,
    }
    store.write_json(REINDEX_STATE_FILE, state)
    try:
        yield
    except Exception as exc:
        state.update({
            "status": "failed",
            "completed_at": _utc_now(),
            "duration_seconds": round(time.monotonic() - started_monotonic, 3),
            "error": safe_reason(reason=str(exc)),
        })
        store.write_json(REINDEX_STATE_FILE, state)
        raise
    else:
        completed_at = _utc_now()
        state.update({
            "status": "succeeded",
            "completed_at": completed_at,
            "duration_seconds": round(time.monotonic() - started_monotonic, 3),
            "last_success_at": completed_at,
            "error": "",
        })
        store.write_json(REINDEX_STATE_FILE, state)
    finally:
        lock.release()


def _lock_held(store: WorkspaceStore) -> bool:
    probe = FileLock(str(store.reindex_lock_file))
    try:
        probe.acquire(timeout=0)
    except Timeout:
        return True
    probe.release()
    return False


def _last_success_at(state: Any) -> str:
    if not isinstance(state, dict):
        return ""
    if state.get("status") == "succeeded":
        return str(state.get("completed_at", "") or "")
    return str(state.get("last_success_at", "") or "")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
