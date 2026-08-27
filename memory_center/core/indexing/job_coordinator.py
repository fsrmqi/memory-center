"""Workspace job coordinator (Phase C).

Authoritative reindex job state lives in SQLite (``graph.db``), replacing
the JSON file as the source of truth while keeping the existing
``workspace-jobs.json`` export as a compatibility mirror.

Implemented contract (docs/decisions/CODE_GRAPH_FOUNDATION_IMPLEMENTATION.md
§8.2–8.4):

- Job records carry scope/request fingerprints, owner identity, a renewal
  lease, and ``retry_of`` lineage. Terminal states are immutable; retries
  create new jobs.
- Admission coalesces an identical request fingerprint onto the active job,
  rejects overlapping scopes with different requests as ``conflict``, and
  allows non-overlapping work to proceed in parallel up to the lock.
- Lease: workers renew every heartbeat interval (5s); readers observing an
  expired lease CAS the job to ``interrupted`` when the owning PID is gone
  and report ``suspected_stalled`` when the PID is still alive (explicit
  cancel or human recovery required — never auto-kill).
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from typing import Any

from memory_center.core.observability.diagnostics import safe_reason
from memory_center.core.storage.workspace import WorkspaceStore

HEARTBEAT_SECONDS = 5.0
# At least 3x the heartbeat interval per the availability model.
LEASE_SECONDS = 15.0
TERMINAL_STATES = frozenset({"completed", "failed", "cancelled", "interrupted", "rejected_budget"})
ACTIVE_STATES = frozenset({"queued", "admitted", "running", "validating", "publishing", "cancel_requested"})

_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY: set[str] = set()


def _utc_ts() -> float:
    return time.time()


class JobCoordinatorError(RuntimeError):
    """Raised when an admission is refused for coordination reasons.

    Subclasses ``ConflictError``-shaped payload structure so CLI/MCP error
    surfaces can format it like other conflicts, but inherits RuntimeError
    to avoid coupling admission policy to the public error model.
    """

    def __init__(self, payload: dict[str, Any]):
        self.payload = payload
        super().__init__(str(payload.get("reason", "job_coordinator_error")))

    @property
    def diagnostics(self) -> dict[str, Any]:
        return dict(self.payload)


def ensure_tables(store: WorkspaceStore) -> None:
    """Create coordinator tables on the shared graph.db database."""
    db_path = str(store.graph_db_path)
    if db_path in _SCHEMA_READY:
        return
    with _SCHEMA_LOCK:
        if db_path in _SCHEMA_READY:
            return
        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS workspace_jobs (
                  job_id TEXT PRIMARY KEY,
                  kind TEXT NOT NULL DEFAULT 'reindex',
                  workspace_id TEXT NOT NULL DEFAULT '',
                  scope_fingerprint TEXT NOT NULL DEFAULT '',
                  request_fingerprint TEXT NOT NULL DEFAULT '',
                  scope_projects TEXT NOT NULL DEFAULT '[]',
                  scope_paths TEXT NOT NULL DEFAULT '[]',
                  owner_session_id TEXT NOT NULL DEFAULT '',
                  owner_process_id INTEGER NOT NULL DEFAULT 0,
                  owner_actor TEXT NOT NULL DEFAULT '',
                  status TEXT NOT NULL DEFAULT 'queued',
                  lease_expires_at REAL NOT NULL DEFAULT 0,
                  heartbeat_at REAL NOT NULL DEFAULT 0,
                  cancel_requested_at REAL,
                  parent_generation TEXT NOT NULL DEFAULT '',
                  staging_generation TEXT NOT NULL DEFAULT '',
                  retry_of TEXT NOT NULL DEFAULT '',
                  created_at REAL NOT NULL DEFAULT 0,
                  started_at REAL,
                  completed_at REAL,
                  failure_code TEXT NOT NULL DEFAULT '',
                  diagnostics_ref TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_workspace_jobs_status ON workspace_jobs(status);
                CREATE TABLE IF NOT EXISTS generation_publications (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  published_generation TEXT NOT NULL,
                  previous_generation TEXT NOT NULL DEFAULT '',
                  publishing_job_id TEXT NOT NULL DEFAULT '',
                  mode TEXT NOT NULL DEFAULT '',
                  outcome TEXT NOT NULL DEFAULT 'published',
                  published_at TEXT NOT NULL DEFAULT (strftime('%s','now'))
                );
                """
            )
            conn.commit()
        finally:
            conn.close()
        _SCHEMA_READY.add(db_path)


def scope_fingerprint(projects: list[str] | None, paths: list[str] | None) -> str:
    return _fingerprint({"projects": sorted(p or "" for p in (projects or [])), "paths": sorted(p or "" for p in (paths or []))})


def request_fingerprint(kind: str, projects: list[str] | None, paths: list[str], *, parallel: bool = True) -> str:
    return _fingerprint({
        "kind": kind,
        "scope": {"projects": sorted(projects or []), "paths": sorted(paths or [])},
        "parallel": bool(parallel),
    })


def _fingerprint(payload: Any) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def _scopes_overlap(projects_a: list[str], paths_a: list[str], projects_b: list[str], paths_b: list[str]) -> bool:
    # An empty project/path filter means full-workspace scope, which
    # overlaps with everything.
    def full(items: list[str]) -> bool:
        return not items

    if full(projects_a) and full(paths_a) or full(projects_b) and full(paths_b):
        return True
    pa, pb = {p or "" for p in projects_a}, {p or "" for p in projects_b}
    ta, tb = {t or "" for t in paths_a}, {t or "" for t in paths_b}
    if projects_a and projects_b:
        return bool(pa & pb)
    if paths_a and paths_b:
        return bool(ta & tb)
    return True


def recover_stale_jobs(store: WorkspaceStore, *, now: float | None = None) -> dict[str, Any]:
    """Apply lease-expiry recovery rules to active jobs.

    Expired lease + dead PID -> CAS to ``interrupted``. Expired lease +
    live PID -> reported as ``suspected_stalled`` and left untouched so a
    slow writer is never auto-killed mid-run.
    """
    ensure_tables(store)
    ts = now if now is not None else _utc_ts()
    recovered: list[str] = []
    stalled: list[dict[str, Any]] = []
    conn = sqlite3.connect(str(store.graph_db_path))
    try:
        rows = conn.execute(
            f"SELECT job_id, status, owner_process_id, lease_expires_at FROM workspace_jobs WHERE status IN ({','.join('?' * len(ACTIVE_STATES))})",
            tuple(sorted(ACTIVE_STATES)),
        ).fetchall()
        for job_id, status, pid, lease_expires_at in rows:
            expired = float(lease_expires_at or 0) <= ts
            if not expired:
                continue
            if pid and _pid_is_alive(int(pid)):
                stalled.append({"job_id": job_id, "status": status, "owner_process_id": int(pid)})
                continue
            changed = conn.execute(
                "UPDATE workspace_jobs SET status='interrupted', completed_at=?, failure_code='lease_interrupted' "
                "WHERE job_id=? AND status=? AND lease_expires_at<=?",
                (_utc_ts(), job_id, status, ts),
            ).rowcount
            if changed:
                recovered.append(job_id)
        conn.commit()
    finally:
        conn.close()
    return {"interrupted": recovered, "suspected_stalled": stalled}


def admit_reindex_job(
    store: WorkspaceStore,
    *,
    kind: str = "reindex",
    projects: list[str] | None = None,
    paths: list[str] | None = None,
    parallel: bool = True,
    parent_generation: str = "",
    staging_generation: str = "",
    owner_actor: str = "",
    owner_session_id: str = "",
) -> dict[str, Any]:
    """Admit one reindex request under fingerprint-based coordination."""
    recovery = recover_stale_jobs(store)
    suspected = recovery.get("suspected_stalled") or []
    if suspected:
        raise JobCoordinatorError({
            "reason": "reindex_conflict",
            "message": "存在疑似停滞的写入任务（lease 过期但进程仍存活）。",
            "suspected_stalled": suspected,
            "next_action": "等待其完成，或显式取消该 job 后重试；不要强制终止。",
        })

    ensure_tables(store)
    projects_l = [p for p in (projects or []) if p]
    paths_l = [p for p in (paths or []) if p]
    sf = scope_fingerprint(projects_l, paths_l)
    rf = request_fingerprint(kind, projects_l, paths_l, parallel=parallel)

    conn = sqlite3.connect(str(store.graph_db_path))
    try:
        active_rows = conn.execute(
            f"SELECT job_id, request_fingerprint, staging_generation, scope_projects, scope_paths"
            f" FROM workspace_jobs WHERE status IN ({','.join('?' * len(ACTIVE_STATES))})",
            tuple(sorted(ACTIVE_STATES)),
        ).fetchall()
        for job_id, active_rf, active_staging, stored_projects_json, stored_paths_json in active_rows:
            if active_rf == rf:
                return {"coalesced": True, "job_id": job_id, "staging_generation": active_staging}
            # Overlapping scope with a different request cannot safely merge
            # once parsing may have started; refuse instead of pre-empting.
            stored_projects = json.loads(stored_projects_json or "[]")
            stored_paths = json.loads(stored_paths_json or "[]")
            if _scopes_overlap(projects_l, paths_l, stored_projects, stored_paths):
                return {
                    "conflict": True,
                    "reason_code": "reindex_conflict",
                    "owner_job_id": job_id,
                    "next_action": "等待 owner job 终态后重新提交，或显式取消 owner job。",
                }
        now = _utc_ts()
        job_id = f"job-{os.urandom(6).hex()}"
        conn.execute(
            "INSERT INTO workspace_jobs(job_id, kind, workspace_id, scope_fingerprint, request_fingerprint,"
            " scope_projects, scope_paths, owner_session_id, owner_process_id, owner_actor, status,"
            " lease_expires_at, heartbeat_at, parent_generation, staging_generation, retry_of, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                job_id,
                kind,
                str(store.workspace_file),
                sf,
                rf,
                json.dumps(projects_l),
                json.dumps(paths_l),
                owner_session_id[:64],
                os.getpid(),
                owner_actor[:64],
                "queued",
                now + LEASE_SECONDS,
                now,
                parent_generation,
                staging_generation,
                "",
                now,
            ),
        )
        conn.commit()
        return {"coalesced": False, "conflict": False, "job_id": job_id}
    finally:
        conn.close()


def mark_stage(store: WorkspaceStore, job_id: str, stage: str) -> bool:
    """Advance a job to a non-terminal stage (running/validating/publishing).

    Terminal states are immutable: the UPDATE excludes them explicitly.
    """
    ensure_tables(store)
    conn = sqlite3.connect(str(store.graph_db_path))
    try:
        now = _utc_ts()
        started_clause = ", started_at=COALESCE(started_at, ?)" if stage == "running" else ""
        params: list[Any] = [stage, now + LEASE_SECONDS, now]
        if stage == "running":
            params.append(now)
        params.extend([job_id, *sorted(TERMINAL_STATES)])
        changed = conn.execute(
            f"UPDATE workspace_jobs SET status=?, lease_expires_at=?, heartbeat_at=?{started_clause}"
            f" WHERE job_id=? AND status NOT IN ({','.join('?' * len(TERMINAL_STATES))})",
            params,
        ).rowcount
        conn.commit()
        return bool(changed)
    finally:
        conn.close()


def record_heartbeat(store: WorkspaceStore, job_id: str) -> None:
    ensure_tables(store)
    conn = sqlite3.connect(str(store.graph_db_path))
    try:
        now = _utc_ts()
        conn.execute(
            "UPDATE workspace_jobs SET lease_expires_at=?, heartbeat_at=? WHERE job_id=? AND status IN ('running','validating','publishing','cancel_requested')",
            (now + LEASE_SECONDS, now, job_id),
        )
        conn.commit()
    finally:
        conn.close()


def request_cancel(store: WorkspaceStore, job_id: str) -> bool:
    """Cooperative cancellation: flag the job; the worker checks at boundaries."""
    ensure_tables(store)
    conn = sqlite3.connect(str(store.graph_db_path))
    try:
        now = _utc_ts()
        changed = conn.execute(
            "UPDATE workspace_jobs SET status='cancel_requested', cancel_requested_at=?"
            " WHERE job_id=? AND status IN ('queued','admitted','running','validating')",
            (now, job_id),
        ).rowcount
        conn.commit()
        return bool(changed)
    finally:
        conn.close()


def cancel_requested(store: WorkspaceStore, job_id: str) -> bool:
    """Whether the worker should stop before the next stage boundary."""
    row = get_job(store, job_id) or {}
    return str(row.get("status", "")) in {"cancel_requested"} or row.get("cancel_requested_at") is not None


def finish_job(
    store: WorkspaceStore,
    job_id: str,
    status: str,
    *,
    failure_code: str = "",
    staging_generation: str = "",
) -> bool:
    """Record a terminal state; terminal states are immutable."""
    if status not in TERMINAL_STATES:
        raise ValueError(f"{status} is not a terminal job state")
    ensure_tables(store)
    conn = sqlite3.connect(str(store.graph_db_path))
    try:
        now = _utc_ts()
        # NOTE: lease_expires_at=0 is a SQL literal, not a placeholder.
        sets = ["status=?", "completed_at=?", "lease_expires_at=0"]
        params: list[Any] = [status, now]
        if failure_code:
            sets.append("failure_code=?")
            params.append(safe_reason(reason=failure_code)[:160])
        if staging_generation:
            sets.append("staging_generation=?")
            params.append(staging_generation)
        params.extend([job_id, *sorted(TERMINAL_STATES)])
        changed = conn.execute(
            f"UPDATE workspace_jobs SET {', '.join(sets)} WHERE job_id=? AND status NOT IN ({','.join('?' * len(TERMINAL_STATES))})",
            params,
        ).rowcount
        conn.commit()
        return bool(changed)
    finally:
        conn.close()


def get_job(store: WorkspaceStore, job_id: str) -> dict[str, Any] | None:
    ensure_tables(store)
    conn = sqlite3.connect(str(store.graph_db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM workspace_jobs WHERE job_id=?", (job_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def retry_job(store: WorkspaceStore, job_id: str, **admission_kwargs: Any) -> dict[str, Any]:
    """Create a replacement job linked via ``retry_of`` (old job stays terminal)."""
    previous = get_job(store, job_id)
    if not previous:
        return {"error": "not_found", "job_id": job_id}
    if previous.get("status") not in TERMINAL_STATES:
        return {"error": "not_terminal", "job_id": job_id, "status": previous.get("status")}
    result = admit_reindex_job(store, **admission_kwargs)
    if result.get("job_id") and not result.get("coalesced"):
        conn = sqlite3.connect(str(store.graph_db_path))
        try:
            conn.execute("UPDATE workspace_jobs SET retry_of=? WHERE job_id=?", (job_id, result["job_id"]))
            conn.commit()
        finally:
            conn.close()
    return result


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True
