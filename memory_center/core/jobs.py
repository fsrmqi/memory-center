"""Small local job registry for deep, interruptible analysis requests."""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from .store import WorkspaceStore

JOBS_FILE = "workspace-jobs.json"
_CANCELLED: set[str] = set()
_GUARD = threading.Lock()


def submit_workspace_job(workspace_file: str, kind: str, work: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    job_id = f"job-{uuid4().hex[:12]}"
    record = {"job_id": job_id, "kind": kind, "status": "queued", "created_at": time.time(), "updated_at": time.time()}
    _upsert(store, record)

    def runner() -> None:
        _upsert(store, {**record, "status": "running", "updated_at": time.time()})
        try:
            result = work()
            if _is_cancelled(job_id):
                _upsert(store, {**record, "status": "cancelled", "updated_at": time.time()})
            else:
                _upsert(store, {**record, "status": "completed", "updated_at": time.time(), "result": result})
        except Exception as exc:  # pragma: no cover - error boundary is exposed via status
            _upsert(store, {**record, "status": "failed", "updated_at": time.time(), "error": str(exc)})

    threading.Thread(target=runner, name=job_id, daemon=True).start()
    return record


def workspace_job_status(workspace_file: str, job_id: str = "", limit: int = 20) -> dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    rows = store.read_json(JOBS_FILE, []) or []
    if job_id:
        return next((row for row in rows if row.get("job_id") == job_id), {"job_id": job_id, "found": False})
    return {"jobs": sorted(rows, key=lambda row: float(row.get("updated_at", 0)), reverse=True)[:limit]}


def cancel_workspace_job(workspace_file: str, job_id: str) -> dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    with _GUARD:
        _CANCELLED.add(job_id)
    current = workspace_job_status(workspace_file, job_id)
    if not current.get("job_id") or current.get("found") is False:
        return {"job_id": job_id, "cancelled": False, "reason": "not_found"}
    _upsert(store, {**current, "status": "cancel_requested", "updated_at": time.time()})
    return {"job_id": job_id, "cancelled": True, "status": "cancel_requested"}


def _is_cancelled(job_id: str) -> bool:
    with _GUARD:
        return job_id in _CANCELLED


def _upsert(store: WorkspaceStore, record: dict[str, Any]) -> None:
    with _GUARD:
        rows = store.read_json(JOBS_FILE, []) or []
        rows = [row for row in rows if row.get("job_id") != record["job_id"]]
        rows.append(record)
        store.write_json(JOBS_FILE, rows[-100:])
