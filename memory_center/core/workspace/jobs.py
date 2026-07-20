"""Small local job registry for deep, interruptible analysis requests."""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from memory_center.core.storage.workspace import WorkspaceStore

JOBS_FILE = "workspace-jobs.json"
PROGRESS_STAGES = frozenset(
    {
        "queued",
        "scanning",
        "parsing",
        "graph",
        "retrieval",
        "semantic",
        "finalizing",
        "completed",
        "failed",
        "cancelled",
        "interrupted",
    }
)
MAX_PROGRESS_EVENTS = 24
_CANCELLED: set[str] = set()
_GUARD = threading.Lock()


def submit_workspace_job(
    workspace_file: str,
    kind: str,
    work: Callable[[], dict[str, Any]],
    *,
    progress_work: Callable[[Callable[[str, int, str], None]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    job_id = f"job-{uuid4().hex[:12]}"
    now = time.time()
    record = {
        "schema_version": 2,
        "job_id": job_id,
        "kind": kind,
        "status": "queued",
        "created_at": now,
        "updated_at": now,
        "progress": _progress("queued", 0, "任务已进入队列", now),
        "progress_events": [_progress("queued", 0, "任务已进入队列", now)],
    }
    _upsert(store, record)

    def runner() -> None:
        _update_progress(store, job_id, "scanning", 5, "正在准备任务输入")
        try:
            result = progress_work(lambda stage, percent, message="": _update_progress(store, job_id, stage, percent, message)) if progress_work else work()
            if _is_cancelled(job_id):
                _finish_job(store, job_id, "cancelled", progress_stage="cancelled", message="任务已取消")
            else:
                _update_progress(store, job_id, "finalizing", 95, "正在整理任务结果")
                _finish_job(store, job_id, "completed", result=result, progress_stage="completed", message="任务已完成")
        except Exception as exc:  # pragma: no cover - error boundary is exposed via status
            from memory_center.core.observability.diagnostics import safe_reason

            _finish_job(store, job_id, "failed", error=safe_reason(reason=str(exc)), progress_stage="failed", message="任务执行失败")

    threading.Thread(target=runner, name=job_id, daemon=True).start()
    return record


def workspace_job_status(workspace_file: str, job_id: str = "", limit: int = 20) -> dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    recover_interrupted_workspace_jobs(store)
    rows = store.read_json_prefer_backend(JOBS_FILE, []) or []
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

    def progress_work(report: Callable[[str, int, str], None]) -> dict[str, Any]:
        from memory_center.core.indexing.reindex import reindex_workspace
        from memory_center.core.workspace.config import load_workspace_config

        return reindex_workspace(
            load_workspace_config(workspace_file),
            WorkspaceStore(workspace_file),
            projects=projects,
            paths=paths,
            progress=report,
        )

    return submit_workspace_job(workspace_file, "reindex", work, progress_work=progress_work)


def recover_interrupted_workspace_jobs(store: WorkspaceStore) -> int:
    """Mark jobs left running by a terminated local process as interrupted."""
    rows = store.read_json_prefer_backend(JOBS_FILE, []) or []
    now = time.time()
    changed = 0
    recovered = []
    for row in rows:
        if row.get("status") == "running" and now - float(row.get("updated_at", now)) > 30:
            progress = _progress("interrupted", int((row.get("progress") or {}).get("percent", 0)), "宿主进程中断", now)
            recovered.append({**row, "status": "interrupted", "updated_at": now, "progress": progress, "progress_events": [*(row.get("progress_events", []) or [])[-(MAX_PROGRESS_EVENTS - 1):], progress]})
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
    _update_progress(store, job_id, str((current.get("progress") or {}).get("stage", "queued")), int((current.get("progress") or {}).get("percent", 0)), "已请求取消")
    current = workspace_job_status(workspace_file, job_id)
    _upsert(store, {**current, "status": "cancel_requested", "updated_at": time.time()})
    return {"job_id": job_id, "cancelled": True, "status": "cancel_requested"}


def _is_cancelled(job_id: str) -> bool:
    with _GUARD:
        return job_id in _CANCELLED


def _upsert(store: WorkspaceStore, record: dict[str, Any]) -> None:
    with _GUARD:
        rows = store.read_json_prefer_backend(JOBS_FILE, []) or []
        rows = [row for row in rows if row.get("job_id") != record["job_id"]]
        rows.append(record)
        store.write_json(JOBS_FILE, rows[-100:])


def _update_progress(store: WorkspaceStore, job_id: str, stage: str, percent: int, message: str = "") -> None:
    if stage not in PROGRESS_STAGES:
        stage = "failed"
        message = "任务报告了未知进度阶段"
    rows = store.read_json_prefer_backend(JOBS_FILE, []) or []
    current = next((row for row in rows if row.get("job_id") == job_id), None)
    if not isinstance(current, dict):
        return
    existing = current.get("progress", {}) or {}
    bounded_percent = max(int(existing.get("percent", 0) or 0), min(100, max(0, int(percent))))
    now = time.time()
    progress = _progress(stage, bounded_percent, message, now)
    events = [*(current.get("progress_events", []) or [])[-(MAX_PROGRESS_EVENTS - 1):], progress]
    _upsert(store, {**current, "status": "running", "updated_at": now, "progress": progress, "progress_events": events})


def _finish_job(
    store: WorkspaceStore,
    job_id: str,
    status: str,
    *,
    result: dict[str, Any] | None = None,
    error: str = "",
    progress_stage: str,
    message: str,
) -> None:
    rows = store.read_json_prefer_backend(JOBS_FILE, []) or []
    current = next((row for row in rows if row.get("job_id") == job_id), None)
    if not isinstance(current, dict):
        return
    now = time.time()
    current_progress = current.get("progress", {}) or {}
    terminal_percent = 100 if status == "completed" else int(current_progress.get("percent", 0) or 0)
    progress = _progress(progress_stage, terminal_percent, message, now)
    record = {
        **current,
        "status": status,
        "updated_at": now,
        "progress": progress,
        "progress_events": [*(current.get("progress_events", []) or [])[-(MAX_PROGRESS_EVENTS - 1):], progress],
    }
    if result is not None:
        record["result"] = result
    if error:
        record["error"] = error
    _upsert(store, record)


def _progress(stage: str, percent: int, message: str, now: float) -> dict[str, Any]:
    return {"stage": stage, "percent": max(0, min(100, int(percent))), "message": message[:160], "updated_at": now}
