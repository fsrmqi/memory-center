"""Persistent local watcher daemon for automatic targeted reindexing."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout

from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.core.workspace.config import load_workspace_config

from .watcher import FileWatcher, WatchEvent, trigger_incremental_reindex

WATCHER_DAEMON_FILE = "watcher-daemon.json"
WATCHER_DAEMON_LOCK = "watcher-daemon.lock"
_TERMINAL_JOB_STATUSES = frozenset({"completed", "failed", "cancelled", "interrupted"})
_MONITORED_JOBS: set[str] = set()
_MONITORED_JOBS_LOCK = threading.Lock()


def watcher_daemon_status(workspace_file: str | Path) -> dict[str, Any]:
    """Read persisted daemon state without starting a watcher."""
    store = WorkspaceStore(workspace_file)
    state = store.read_json(WATCHER_DAEMON_FILE, {}) or {}
    if not state:
        return {"status": "stopped", "active": False, "configured": False}
    pid = int(state.get("pid", 0) or 0)
    active = state.get("status") == "running" and _pid_alive(pid)
    status = "running" if active else ("stale" if state.get("status") == "running" else str(state.get("status", "stopped")))
    return {**state, "status": status, "active": active, "configured": True}


def start_watcher_daemon(
    workspace_file: str | Path,
    *,
    poll_interval: float = 5.0,
    debounce_seconds: float = 2.0,
) -> dict[str, Any]:
    """Launch one detached watcher process for a workspace."""
    workspace = str(Path(workspace_file).expanduser().resolve())
    load_workspace_config(workspace)
    existing = watcher_daemon_status(workspace)
    if existing.get("active"):
        return {**existing, "started": False, "reason": "already_running"}
    if poll_interval < 0.2 or debounce_seconds < 0.0:
        raise ValueError("poll_interval must be at least 0.2 seconds and debounce_seconds must be non-negative")
    command = [
        sys.executable,
        "-m",
        "memory_center.cli.main",
        "watcher-run",
        "--workspace",
        workspace,
        "--poll-interval",
        str(poll_interval),
        "--debounce-seconds",
        str(debounce_seconds),
    ]
    with open(os.devnull, "wb") as sink:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=sink, stderr=sink, start_new_session=True)
    return {
        "status": "starting",
        "active": True,
        "started": True,
        "pid": process.pid,
        "workspace_file": workspace,
        "poll_interval": poll_interval,
        "debounce_seconds": debounce_seconds,
    }


def stop_watcher_daemon(workspace_file: str | Path) -> dict[str, Any]:
    """Request graceful watcher shutdown through SIGTERM."""
    current = watcher_daemon_status(workspace_file)
    if not current.get("active"):
        return {**current, "stopped": False, "reason": "not_running"}
    pid = int(current["pid"])
    os.kill(pid, signal.SIGTERM)
    return {**current, "status": "stopping", "active": True, "stopped": True}


def run_watcher_daemon(
    workspace_file: str | Path,
    *,
    poll_interval: float = 5.0,
    debounce_seconds: float = 2.0,
) -> dict[str, Any]:
    """Run the daemon in the foreground; intended only for the detached CLI child."""
    workspace = str(Path(workspace_file).expanduser().resolve())
    store = WorkspaceStore(workspace)
    config = load_workspace_config(workspace)
    stop_event = threading.Event()
    lock = FileLock(str(store.base_dir / WATCHER_DAEMON_LOCK))
    try:
        lock.acquire(timeout=0)
    except Timeout as exc:
        raise RuntimeError("watcher daemon is already running for this workspace") from exc

    watcher = FileWatcher(config.root_path, poll_interval=poll_interval, debounce_seconds=debounce_seconds)
    watcher.on_change(lambda events: record_watcher_batch(workspace, events))
    previous_handlers = _install_stop_handlers(stop_event)
    _write_state(
        store,
        {
            "schema_version": 1,
            "status": "running",
            "pid": os.getpid(),
            "workspace_file": workspace,
            "root": str(config.root_path),
            "started_at": time.time(),
            "updated_at": time.time(),
            "poll_interval": poll_interval,
            "debounce_seconds": debounce_seconds,
            "event_batches": 0,
            "changed_files": 0,
        },
    )
    try:
        watcher.start()
        while not stop_event.wait(0.5):
            pass
        return {"status": "stopped", "pid": os.getpid()}
    except Exception as exc:
        _update_state(store, status="failed", error=str(exc)[:200])
        raise
    finally:
        watcher.stop()
        _restore_stop_handlers(previous_handlers)
        _update_state(store, status="stopped", stopped_at=time.time())
        lock.release()


def record_watcher_batch(workspace_file: str | Path, events: list[WatchEvent]) -> dict[str, Any]:
    """Persist one debounced event batch and queue its bounded partial reindex."""
    changed_paths = sorted({event.path for event in events if event.path})[:200]
    result = trigger_incremental_reindex(workspace_file, changed_paths)
    store = WorkspaceStore(workspace_file)
    _update_state(
        store,
        updated_at=time.time(),
        event_batches=int((store.read_json(WATCHER_DAEMON_FILE, {}) or {}).get("event_batches", 0) or 0) + 1,
        changed_files=int((store.read_json(WATCHER_DAEMON_FILE, {}) or {}).get("changed_files", 0) or 0) + len(changed_paths),
        last_event_at=time.time(),
        last_changed_paths=changed_paths[:24],
        last_reindex_job=(result.get("reindex_job", {}) or {}).get("job_id", ""),
        last_result={"status": result.get("status", "unknown"), "changed_files": result.get("changed_files", 0)},
    )
    job = result.get("reindex_job", {}) or {}
    job_id = str(job.get("job_id", "") or "")
    if job_id:
        _monitor_change_report(workspace_file, job_id, changed_paths, result)
    return result


def _monitor_change_report(workspace_file: str | Path, job_id: str, changed_paths: list[str], trigger_result: dict[str, Any]) -> None:
    with _MONITORED_JOBS_LOCK:
        if job_id in _MONITORED_JOBS:
            return
        _MONITORED_JOBS.add(job_id)

    def monitor() -> None:
        from memory_center.core.workspace.jobs import workspace_job_status

        from .change_reports import record_change_impact_report

        try:
            for _ in range(1_800):  # 30 minutes at one low-cost status read per second.
                job = workspace_job_status(str(workspace_file), job_id)
                if job.get("found") is False:
                    _update_state(WorkspaceStore(workspace_file), last_change_report_status="job_not_found")
                    return
                if str(job.get("status", "")) in _TERMINAL_JOB_STATUSES:
                    report = record_change_impact_report(
                        workspace_file,
                        changed_paths=changed_paths,
                        trigger_result=trigger_result,
                        job=job,
                    )
                    _update_state(
                        WorkspaceStore(workspace_file),
                        last_change_report=report["report_id"],
                        last_change_risk=report["risk_level"],
                        last_change_report_status=report["status"],
                    )
                    return
                time.sleep(1.0)
            _update_state(WorkspaceStore(workspace_file), last_change_report_status="timeout")
        finally:
            with _MONITORED_JOBS_LOCK:
                _MONITORED_JOBS.discard(job_id)

    threading.Thread(target=monitor, name=f"watch-report-{job_id}", daemon=True).start()


def _write_state(store: WorkspaceStore, state: dict[str, Any]) -> None:
    store.write_json(WATCHER_DAEMON_FILE, state)


def _update_state(store: WorkspaceStore, **changes: Any) -> None:
    current = store.read_json(WATCHER_DAEMON_FILE, {}) or {}
    _write_state(store, {**current, **changes, "updated_at": time.time()})


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _install_stop_handlers(stop_event: threading.Event) -> dict[int, Any]:
    previous: dict[int, Any] = {}
    for signum in (signal.SIGTERM, signal.SIGINT):
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, lambda _signum, _frame: stop_event.set())
    return previous


def _restore_stop_handlers(previous: dict[int, Any]) -> None:
    for signum, handler in previous.items():
        signal.signal(signum, handler)
