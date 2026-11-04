"""Phase C job coordinator tests (CODE_GRAPH_FOUNDATION_IMPLEMENTATION §8).

Covers fingerprint-based coalescing/conflict admission, terminal state
immutability, retry lineage, lease/PID recovery rules, atomic-publish
failure rollback, publish-smoke failure handling, and cooperative
cancellation at the publishing boundary.
"""
from __future__ import annotations

import sqlite3
import time

import pytest

from memory_center.core.indexing import job_coordinator as jc
from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.core.workspace.config import load_workspace_config


# ---------------------------------------------------------------------------
# Unit: fingerprints and admission
# ---------------------------------------------------------------------------


def test_identical_requests_coalesce_onto_one_job(demo_workspace_indexed):
    store = WorkspaceStore(demo_workspace_indexed)
    first = jc.admit_reindex_job(store, projects=["api"])
    assert first.get("coalesced") is False
    second = jc.admit_reindex_job(store, projects=["api"])
    assert second.get("coalesced") is True
    assert second["job_id"] == first["job_id"]


def test_non_overlapping_scopes_do_not_conflict(demo_workspace_indexed):
    store = WorkspaceStore(demo_workspace_indexed)
    api = jc.admit_reindex_job(store, projects=["api"])
    task = jc.admit_reindex_job(store, projects=["task-service"])
    assert api.get("conflict") is False
    assert task.get("conflict") is False
    assert task["job_id"] != api["job_id"]
    jc.finish_job(store, api["job_id"], "cancelled")
    jc.finish_job(store, task["job_id"], "cancelled")


def test_full_scope_conflicts_with_any_active_scope(demo_workspace_indexed):
    store = WorkspaceStore(demo_workspace_indexed)
    scoped = jc.admit_reindex_job(store, projects=["api"])
    full = jc.admit_reindex_job(store)
    assert scoped.get("conflict") is False
    assert full.get("conflict") is True
    assert full["owner_job_id"] == scoped["job_id"]
    jc.finish_job(store, scoped["job_id"], "cancelled")


def test_terminal_states_are_immutable_and_retry_links_lineage(demo_workspace_indexed):
    store = WorkspaceStore(demo_workspace_indexed)
    job_id = str(jc.admit_reindex_job(store, paths=["x"])["job_id"])
    assert jc.finish_job(store, job_id, "completed") is True
    assert jc.finish_job(store, job_id, "failed", failure_code="late_overwrite") is False
    row = jc.get_job(store, job_id)
    assert row["status"] == "completed"

    retry = jc.retry_job(store, job_id, paths=["x"])
    assert retry.get("coalesced") is not True
    retried_row = jc.get_job(store, retry["job_id"])
    assert retried_row["retry_of"] == job_id
    # lineage keeps old evidence: no mutation of the terminal predecessor
    assert jc.get_job(store, job_id)["status"] == "completed"


def test_finish_rejects_non_terminal_status(demo_workspace_indexed):
    store = WorkspaceStore(demo_workspace_indexed)
    job_id = str(jc.admit_reindex_job(store, paths=["y"])["job_id"])
    with pytest.raises(ValueError):
        jc.finish_job(store, job_id, "running")
    jc.finish_job(store, job_id, "failed", failure_code="cleanup")


# ---------------------------------------------------------------------------
# Lease / PID recovery
# ---------------------------------------------------------------------------


def test_expired_lease_with_dead_pid_is_interrupted(demo_workspace_indexed):
    store = WorkspaceStore(demo_workspace_indexed)
    job_id = str(jc.admit_reindex_job(store, paths=["z"])["job_id"])
    conn = sqlite3.connect(str(store.graph_db_path))
    conn.execute(
        "UPDATE workspace_jobs SET status='running', owner_process_id=999999999, lease_expires_at=? WHERE job_id=?",
        (time.time() - 60, job_id),
    )
    conn.commit()
    conn.close()

    recovery = jc.recover_stale_jobs(store)
    assert job_id in recovery["interrupted"]
    assert jc.get_job(store, job_id)["status"] == "interrupted"
    assert jc.get_job(store, job_id)["failure_code"] == "lease_interrupted"


def test_expired_lease_with_live_pid_is_reported_not_killed(demo_workspace_indexed):
    store = WorkspaceStore(demo_workspace_indexed)
    import os

    job_id = str(jc.admit_reindex_job(store, paths=["w"])["job_id"])
    conn = sqlite3.connect(str(store.graph_db_path))
    conn.execute(
        "UPDATE workspace_jobs SET status='running', owner_process_id=?, lease_expires_at=? WHERE job_id=?",
        (os.getpid(), time.time() - 60, job_id),
    )
    conn.commit()
    conn.close()

    recovery = jc.recover_stale_jobs(store)
    stalled_ids = {row["job_id"] for row in recovery["suspected_stalled"]}
    assert job_id in stalled_ids
    assert jc.get_job(store, job_id)["status"] == "running"


# ---------------------------------------------------------------------------
# Integration: coordination inside reindex_workspace
# ---------------------------------------------------------------------------


def test_publish_smoke_failure_rolls_back_to_previous_generation(demo_workspace_indexed, monkeypatch):
    from memory_center.core.indexing import reindex as reindex_module
    from memory_center.core.indexing.control_plane import index_control_status

    store = WorkspaceStore(demo_workspace_indexed)
    previous_generation = str(index_control_status(store)["active_generation"])

    def broken_smoke(_store, _generation):
        return {"ok": False, "reason": "injected_smoke_failure"}

    monkeypatch.setattr(reindex_module, "_publish_smoke", broken_smoke)
    with pytest.raises(RuntimeError, match="publish_smoke_failed"):
        counts = reindex_module.reindex_workspace(load_workspace_config(demo_workspace_indexed), store)
        job_id = str(counts["job_id"])

    # Rollback restored the previous pointer and the failed job is terminal.
    assert index_control_status(store)["active_generation"] == previous_generation
    conn = sqlite3.connect(str(store.graph_db_path))
    failed_rows = conn.execute(
        "SELECT job_id, failure_code FROM workspace_jobs WHERE status='failed'"
    ).fetchall()
    outcomes = [row[0] for row in conn.execute("SELECT outcome FROM generation_publications").fetchall()]
    conn.close()
    smoke_jobs = [row for row in failed_rows if "publish_smoke_failed" in row[1]]
    assert smoke_jobs
    assert "publish_smoke_failed" in outcomes


def test_crash_during_publish_transaction_keeps_previous_active(demo_workspace_indexed, monkeypatch):
    from memory_center.core.indexing import reindex as reindex_module
    from memory_center.core.indexing.control_plane import index_control_status

    store = WorkspaceStore(demo_workspace_indexed)
    previous_generation = str(index_control_status(store)["active_generation"])
    calls = {"n": 0}
    original = WorkspaceStore.publish_generation_payloads

    def crashing_publish(self, payloads, *, publication=None):
        calls["n"] += 1
        raise sqlite3.OperationalError("injected transaction failure")

    monkeypatch.setattr(WorkspaceStore, "publish_generation_payloads", crashing_publish)
    try:
        with pytest.raises(sqlite3.OperationalError):
            reindex_module.reindex_workspace(load_workspace_config(demo_workspace_indexed), store)
    finally:
        monkeypatch.setattr(WorkspaceStore, "publish_generation_payloads", original)

    assert calls["n"] == 1
    assert index_control_status(store)["active_generation"] == previous_generation
    job_states = []
    conn = sqlite3.connect(str(store.graph_db_path))
    rows = conn.execute("SELECT status FROM workspace_jobs").fetchall()
    conn.close()
    job_states = [row[0] for row in rows]
    assert "publishing" not in job_states  # no permanent active stage rows
    assert "failed" in job_states


def test_cooperative_cancel_before_publishing_marks_cancelled(demo_workspace_indexed, monkeypatch):
    from memory_center.core.indexing import reindex as reindex_module
    from memory_center.core.indexing.control_plane import index_control_status
    from memory_center.core.workspace.jobs import WorkspaceJobCancelled

    store = WorkspaceStore(demo_workspace_indexed)
    previous_generation = str(index_control_status(store)["active_generation"])
    monkeypatch.setattr(reindex_module.job_coordinator, "cancel_requested", lambda _store, _job_id: True)

    with pytest.raises(WorkspaceJobCancelled):
        reindex_module.reindex_workspace(load_workspace_config(demo_workspace_indexed), store)

    assert index_control_status(store)["active_generation"] == previous_generation
    conn = sqlite3.connect(str(store.graph_db_path))
    statuses = [row[0] for row in conn.execute("SELECT status FROM workspace_jobs").fetchall()]
    conn.close()
    assert "cancelled" in statuses
    assert "publishing" not in statuses


def test_successful_run_records_completed_job_and_publication_audit(demo_workspace_indexed):
    from memory_center.core.indexing import reindex as reindex_module
    from memory_center.core.indexing.control_plane import index_control_status

    store = WorkspaceStore(demo_workspace_indexed)
    counts = reindex_module.reindex_workspace(load_workspace_config(demo_workspace_indexed), store)
    job = jc.get_job(store, str(counts["job_id"]))
    assert job["status"] == "completed"
    assert index_control_status(store)["active_generation"]
    conn = sqlite3.connect(str(store.graph_db_path))
    rows = conn.execute(
        "SELECT published_generation, publishing_job_id, outcome FROM generation_publications ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    assert rows[0] and rows[1] == counts["job_id"] and rows[2] == "published"
