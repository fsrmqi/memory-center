"""Small local job registry for deep, interruptible analysis requests."""

from __future__ import annotations

import os
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
_HEARTBEAT_SECONDS = 5.0


class WorkspaceJobCancelled(RuntimeError):
    """任务在一个可协作的阶段确认了取消请求。"""


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
        "schema_version": 3,
        "job_id": job_id,
        "kind": kind,
        "status": "queued",
        "created_at": now,
        "updated_at": now,
        "runner_pid": None,
        "progress": _progress("queued", 0, "任务已进入队列", now),
        "progress_events": [_progress("queued", 0, "任务已进入队列", now)],
    }
    _upsert(store, record)

    def runner() -> None:
        # SQLite connections are thread-affine. The worker must own its store
        # instead of reusing the caller's connection created on the submit thread.
        worker_store = WorkspaceStore(workspace_file)
        started_at = time.time()
        _upsert(
            worker_store,
            {
                **record,
                "status": "running",
                "runner_pid": os.getpid(),
                "started_at": started_at,
                "updated_at": started_at,
            },
        )
        _update_progress(worker_store, job_id, "scanning", 5, "正在准备任务输入")
        stopped = threading.Event()

        def heartbeat() -> None:
            while not stopped.wait(_HEARTBEAT_SECONDS):
                _heartbeat(worker_store, job_id)

        heartbeat_thread = threading.Thread(target=heartbeat, name=f"{job_id}-heartbeat", daemon=True)
        heartbeat_thread.start()

        def report(stage: str, percent: int, message: str = "") -> None:
            if _is_cancel_requested(worker_store, job_id):
                raise WorkspaceJobCancelled("任务已取消")
            _update_progress(worker_store, job_id, stage, percent, message)

        try:
            report("scanning", 5, "正在准备任务输入")
            result = progress_work(report) if progress_work else work()
            if _is_cancel_requested(worker_store, job_id):
                _finish_job(worker_store, job_id, "cancelled", progress_stage="cancelled", message="任务已取消")
            else:
                _update_progress(worker_store, job_id, "finalizing", 95, "正在整理任务结果")
                _finish_job(
                    worker_store, job_id, "completed", result=result, progress_stage="completed", message="任务已完成"
                )
        except WorkspaceJobCancelled:
            _finish_job(worker_store, job_id, "cancelled", progress_stage="cancelled", message="任务已取消")
        except Exception as exc:  # pragma: no cover - error boundary is exposed via status
            from memory_center.core.observability.diagnostics import safe_reason

            _finish_job(
                worker_store,
                job_id,
                "failed",
                error=safe_reason(reason=str(exc)),
                progress_stage="failed",
                message="任务执行失败",
            )
        finally:
            stopped.set()

    threading.Thread(target=runner, name=job_id, daemon=True).start()
    return record


def workspace_job_status(workspace_file: str, job_id: str = "", limit: int = 20) -> dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    recover_interrupted_workspace_jobs(store)
    rows = store.read_json_prefer_backend(JOBS_FILE, []) or []
    # Additive Phase C view: active jobs from the SQLite coordinator ledger
    # (authoritative for reindex) ride along so one status surface shows both.
    coordinator_active: list[dict[str, Any]] = []
    try:
        from memory_center.core.indexing.job_coordinator import ACTIVE_STATES, ensure_tables

        ensure_tables(store)
        import sqlite3 as _sqlite3

        conn = _sqlite3.connect(str(store.graph_db_path))
        conn.row_factory = _sqlite3.Row
        crows = conn.execute(
            f"SELECT job_id, kind, status, staging_generation, owner_process_id FROM workspace_jobs"
            f" WHERE status IN ({','.join('?' * len(ACTIVE_STATES))}) ORDER BY created_at DESC LIMIT 10",
            tuple(sorted(ACTIVE_STATES)),
        ).fetchall()
        conn.close()
        coordinator_active = [dict(row) for row in crows]
    except Exception:
        coordinator_active = []
    if job_id:
        row = next((row for row in rows if row.get("job_id") == job_id), None)
        view = _job_view(row) if isinstance(row, dict) else {"job_id": job_id, "found": False}
        matched = next((c for c in coordinator_active if c.get("job_id") == job_id), None)
        if matched is not None:
            view["coordinator"] = matched
        elif isinstance(view, dict) and view.get("found") is False:
            found_coord = next((c for c in coordinator_active if c.get("job_id") == job_id), None)
            if found_coord is not None:
                view = {"job_id": job_id, "found": True, "coordinator": found_coord}
        return view
    return {"jobs": [_job_view(row) for row in selected_rows(rows, limit)], "coordinator_active": coordinator_active}


def selected_rows(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: float(row.get("updated_at", 0)), reverse=True)[:limit]


def submit_reindex_workspace_job(
    workspace_file: str, *, projects: list[str] | None = None, paths: list[str] | None = None
) -> dict[str, Any]:
    """Schedule a resumable-status reindex without blocking an Agent request."""
    existing = workspace_job_status(workspace_file, limit=100).get("jobs", [])
    active = next(
        (
            row
            for row in existing
            if row.get("kind") == "reindex" and row.get("status") in {"queued", "running", "cancel_requested"}
        ),
        None,
    )
    if active:
        return {**active, "coalesced": True}

    def work() -> dict[str, Any]:
        from memory_center.core.indexing.reindex import reindex_workspace
        from memory_center.core.workspace.config import load_workspace_config

        return reindex_workspace(
            load_workspace_config(workspace_file), WorkspaceStore(workspace_file), projects=projects, paths=paths
        )

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
        runner_pid = row.get("runner_pid")
        if row.get("status") == "running" and runner_pid and not _pid_is_alive(int(runner_pid)):
            progress = _progress("interrupted", int((row.get("progress") or {}).get("percent", 0)), "宿主进程中断", now)
            recovered.append(
                {
                    **row,
                    "status": "interrupted",
                    "updated_at": now,
                    "progress": progress,
                    "progress_events": [
                        *(row.get("progress_events", []) or [])[-(MAX_PROGRESS_EVENTS - 1) :],
                        progress,
                    ],
                }
            )
            changed += 1
        else:
            recovered.append(row)
    if changed:
        store.write_json(JOBS_FILE, recovered[-100:])
    return changed


def cancel_workspace_job(workspace_file: str, job_id: str) -> dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    current = workspace_job_status(workspace_file, job_id)
    if not current.get("job_id") or current.get("found") is False:
        # Not in the JSON registry: it may be a Phase C coordinator job.
        try:
            from memory_center.core.indexing.job_coordinator import request_cancel

            if request_cancel(store, job_id):
                return {"job_id": job_id, "cancelled": True, "status": "cancel_requested", "coordinator": True}
        except Exception:
            pass
        return {"job_id": job_id, "cancelled": False, "reason": "not_found"}
    coordinator_flagged = False
    try:
        from memory_center.core.indexing.job_coordinator import request_cancel

        if request_cancel(store, job_id):
            coordinator_flagged = True
    except Exception:
        pass
    _update_progress(
        store,
        job_id,
        str((current.get("progress") or {}).get("stage", "queued")),
        int((current.get("progress") or {}).get("percent", 0)),
        "已请求取消",
    )
    current = workspace_job_status(workspace_file, job_id)
    _upsert(store, {**current, "status": "cancel_requested", "updated_at": time.time()})
    return {"job_id": job_id, "cancelled": True, "status": "cancel_requested", "coordinator": coordinator_flagged}


def _is_cancelled(job_id: str) -> bool:
    with _GUARD:
        return job_id in _CANCELLED


def _is_cancel_requested(store: WorkspaceStore, job_id: str) -> bool:
    current = workspace_job_status(store.workspace_file, job_id)
    return current.get("status") == "cancel_requested" or _is_cancelled(job_id)


def _heartbeat(store: WorkspaceStore, job_id: str) -> None:
    rows = store.read_json_prefer_backend(JOBS_FILE, []) or []
    current = next((row for row in rows if row.get("job_id") == job_id), None)
    if isinstance(current, dict) and current.get("status") in {"running", "cancel_requested"}:
        _upsert(store, {**current, "updated_at": time.time()})


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


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
    events = [*(current.get("progress_events", []) or [])[-(MAX_PROGRESS_EVENTS - 1) :], progress]
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
        "progress_events": [*(current.get("progress_events", []) or [])[-(MAX_PROGRESS_EVENTS - 1) :], progress],
    }
    if result is not None:
        record["result"] = result
    if error:
        record["error"] = error
    _upsert(store, record)


def _progress(stage: str, percent: int, message: str, now: float) -> dict[str, Any]:
    return {"stage": stage, "percent": max(0, min(100, int(percent))), "message": message[:160], "updated_at": now}


def _job_view(record: dict[str, Any]) -> dict[str, Any]:
    """Add presentation-safe long-task guidance without changing stored history."""
    now = time.time()
    updated_at = float(record.get("updated_at") or now)
    started_at = float(record.get("started_at") or record.get("created_at") or updated_at)
    elapsed_ms = max(0, round((now - started_at) * 1000))
    progress = record.get("progress") or {}
    percent = min(100, max(0, int(progress.get("percent", 0) or 0)))
    status = str(record.get("status", "queued") or "queued")
    estimated_remaining_ms: int | None = None
    if status in {"running", "cancel_requested"} and 0 < percent < 100 and elapsed_ms > 0:
        estimated_remaining_ms = max(0, round(elapsed_ms * (100 - percent) / percent))
    if status in {"queued", "running", "cancel_requested"}:
        recovery_action = {"action": "poll_job_status", "job_id": record.get("job_id", ""), "after_seconds": 3}
    elif status in {"failed", "interrupted"} and record.get("kind") == "reindex":
        recovery_action = {"action": "job_reindex", "reason": "重新提交索引任务；不会删除现有 generation。"}
    elif status == "cancelled":
        recovery_action = {"action": "job_reindex", "reason": "按需重新提交取消前的目标范围。"}
    else:
        recovery_action = {"action": "none"}
    return {
        **record,
        "progress_percent": percent,
        "elapsed_ms": elapsed_ms,
        "last_update_age_ms": max(0, round((now - updated_at) * 1000)),
        "estimated_remaining_ms": estimated_remaining_ms,
        "can_cancel": status in {"queued", "running", "cancel_requested"},
        "recovery_action": recovery_action,
    }
