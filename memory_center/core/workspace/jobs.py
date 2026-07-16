"""Small local job registry for deep, interruptible analysis requests."""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from memory_center.core.storage.workspace import WorkspaceStore

JOBS_FILE = "workspace-jobs.json"
_CANCELLED: set[str] = set()
_GUARD = threading.Lock()


def submit_workspace_job(workspace_file: str, kind: str, work: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    job_id = f"job-{uuid4().hex[:12]}"
    record = {"schema_version": 1, "job_id": job_id, "kind": kind, "status": "queued", "created_at": time.time(), "updated_at": time.time(), "progress": {"stage": "queued", "percent": 0}}
    _upsert(store, record)

    def runner() -> None:
        _upsert(store, {**record, "status": "running", "updated_at": time.time(), "progress": {"stage": "running", "percent": 10}})
        try:
            result = work()
            if _is_cancelled(job_id):
                _upsert(store, {**record, "status": "cancelled", "updated_at": time.time(), "progress": {"stage": "cancelled", "percent": 100}})
            else:
                _upsert(store, {**record, "status": "completed", "updated_at": time.time(), "result": result, "progress": {"stage": "completed", "percent": 100}})
        except Exception as exc:  # pragma: no cover - error boundary is exposed via status
            _upsert(store, {**record, "status": "failed", "updated_at": time.time(), "error": str(exc), "progress": {"stage": "failed", "percent": 100}})

    threading.Thread(target=runner, name=job_id, daemon=True).start()
    return record


def workspace_job_status(workspace_file: str, job_id: str = "", limit: int = 20) -> dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    recover_interrupted_workspace_jobs(store)
    rows = store.read_json(JOBS_FILE, []) or []
    if job_id:
        return next((row for row in rows if row.get("job_id") == job_id), {"job_id": job_id, "found": False})
    return {"jobs": sorted(rows, key=lambda row: float(row.get("updated_at", 0)), reverse=True)[:limit]}


def submit_reindex_workspace_job(workspace_file: str, *, projects: list[str] | None = None, paths: list[str] | None = None) -> dict[str, Any]:
    """Schedule a resumable-status reindex without blocking an Agent request."""
    existing = workspace_job_status(workspace_file, limit=100).get("jobs", [])
    active = next((row for row in existing if row.get("kind") == "reindex" and row.get("status") in {"queued", "running", "cancel_requested"}), None)
    if active:
        return {**active, "coalesced": True}
    def work() -> dict[str, Any]:
        from memory_center.core.indexing.reindex import reindex_workspace
        from memory_center.core.workspace.config import load_workspace_config
        return reindex_workspace(load_workspace_config(workspace_file), WorkspaceStore(workspace_file), projects=projects, paths=paths)
    return submit_workspace_job(workspace_file, "reindex", work)


def recover_interrupted_workspace_jobs(store: WorkspaceStore) -> int:
    """Mark jobs left running by a terminated local process as interrupted."""
    rows = store.read_json(JOBS_FILE, []) or []
    now = time.time()
    changed = 0
    recovered = []
    for row in rows:
        if row.get("status") == "running" and now - float(row.get("updated_at", now)) > 30:
            recovered.append({**row, "status": "interrupted", "updated_at": now, "progress": {"stage": "interrupted", "percent": int((row.get("progress") or {}).get("percent", 0))}})
            changed += 1
        else:
            recovered.append(row)
    if changed:
        store.write_json(JOBS_FILE, recovered[-100:])
    return changed


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
