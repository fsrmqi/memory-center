"""Generation-local staging tests (task: staging + publish-only merge).

Verifies that a reindex run buffers merged intermediate indexes in a
generation-local overlay and commits them atomically at publish, so that:

- failed / cancelled runs leave the previous active generation and its
  intermediates intact (nothing half-published);
- a run's staged artifacts are not visible to readers until publish;
- non-overlapping project refreshes keep their own staging without
  clobbering each other;
- the canonical intermediate indexes only change when a run publishes.
"""
from __future__ import annotations

import json
import threading
import time

import pytest

from memory_center.core.indexing import job_coordinator as jc
from memory_center.core.indexing.control_plane import index_control_status
from memory_center.core.indexing.staging import STAGED_INDEXES, IndexStaging, with_staging
from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.core.workspace.config import load_workspace_config


# ---------------------------------------------------------------------------
# Unit: IndexStaging overlay semantics
# ---------------------------------------------------------------------------


def _memory_backend_snapshot(store, name: str):
    return store.memory_backend().read_index(name)


def test_staging_writes_are_not_visible_until_publish(demo_workspace_indexed):
    store = WorkspaceStore(demo_workspace_indexed)
    staging = with_staging(store)
    staging.write_json("file-index.json", [{"path": "staged-only-row"}])
    # Reader (even through the same store) still sees canonical.
    canonical = store.read_json_prefer_backend("file-index.json", [])
    assert all(row.get("path") != "staged-only-row" for row in canonical)
    # Staging reader sees the overlay.
    staged = staging.read_json_prefer_backend("file-index.json", [])
    assert any(row.get("path") == "staged-only-row" for row in staged)
    # After publish, canonical has it and staging clears.
    staging.publish()
    canonical2 = store.read_json_prefer_backend("file-index.json", [])
    assert any(row.get("path") == "staged-only-row" for row in canonical2)
    assert staging.staged_names() == []


def test_failed_run_leaves_canonical_untouched(demo_workspace_indexed):
    """A run that writes staging but raises before publish must not touch
    the canonical intermediates at all."""
    store = WorkspaceStore(demo_workspace_indexed)
    before = {
        name: store.read_json_prefer_backend(name, None)
        for name in ("file-index.json", "api-index.json", "service-topology.json")
    }
    staging = with_staging(store)
    staging.write_json("file-index.json", [{"path": "ghost"}])
    staging.write_json("api-index.json", [{"path": "ghost-api"}])
    # Simulate a failure before publish: just drop the staging wrapper.
    del staging
    after = {
        name: store.read_json_prefer_backend(name, None)
        for name in ("file-index.json", "api-index.json", "service-topology.json")
    }
    assert before == after, "canonical intermediates must be unchanged after a failed run"


def test_non_staged_diagnostics_write_through(demo_workspace_indexed):
    store = WorkspaceStore(demo_workspace_indexed)
    staging = with_staging(store)
    staging.write_json("graph-summary.json", {"marker": "diag"})
    # graph-summary is not a shard input; it goes straight to canonical.
    canonical = store.read_json_prefer_backend("graph-summary.json", {})
    assert canonical.get("marker") == "diag"
    assert "graph-summary.json" not in staging.staged_names()


def test_staged_names_only_contains_shard_indexes(demo_workspace_indexed):
    staging = with_staging(WorkspaceStore(demo_workspace_indexed))
    staging.write_json("file-index.json", [])
    staging.write_json("graph-summary.json", {})
    assert set(staging.staged_names()) == {"file-index.json"}


# ---------------------------------------------------------------------------
# Integration: staging inside reindex_workspace
# ---------------------------------------------------------------------------


def test_staging_run_produces_same_canonical_as_legacy(demo_workspace_indexed):
    """After a staging-based reindex, the canonical indexes must be complete
    and the generation published (no partial intermediate visible)."""
    from memory_center.core.indexing.reindex import reindex_workspace, _publish_smoke

    store = WorkspaceStore(demo_workspace_indexed)
    before_files = store.read_json_prefer_backend("file-index.json", [])
    counts = reindex_workspace(load_workspace_config(demo_workspace_indexed), store)
    after_files = store.read_json_prefer_backend("file-index.json", [])
    # Same file set after a full re-publish.
    assert sorted(f.get("path") for f in before_files) == sorted(f.get("path") for f in after_files)
    assert _publish_smoke(store, index_control_status(store)["active_generation"])["ok"] is True
    job = jc.get_job(store, counts["job_id"])
    assert job["status"] == "completed"


def test_cancelled_before_publish_leaves_previous_generation(demo_workspace_indexed, monkeypatch):
    from memory_center.core.indexing import reindex as reindex_module
    from memory_center.core.workspace.jobs import WorkspaceJobCancelled

    store = WorkspaceStore(demo_workspace_indexed)
    previous = index_control_status(store)["active_generation"]
    monkeypatch.setattr(reindex_module.job_coordinator, "cancel_requested", lambda _s, _j: True)
    with pytest.raises(WorkspaceJobCancelled):
        reindex_module.reindex_workspace(load_workspace_config(demo_workspace_indexed), store)
    # active generation unchanged, staged overlays never published
    assert index_control_status(store)["active_generation"] == previous
    conn = store.memory_backend().connect()
    statuses = [row[0] for row in conn.execute("SELECT status FROM workspace_jobs")]
    conn.close()
    assert "cancelled" in statuses


def test_parallel_non_overlapping_refresh_keeps_both_projects(demo_workspace_indexed):
    """Two sequential non-overlapping project refreshes (serialized by the
    workspace lock, as in production) must each publish their own slice and
    never drop the other project's files."""
    from memory_center.core.indexing.reindex import reindex_workspace

    store = WorkspaceStore(demo_workspace_indexed)
    config = load_workspace_config(demo_workspace_indexed)

    def project_paths(project: str) -> set[str]:
        return {
            str(row.get("path", ""))
            for row in store.read_json_prefer_backend("file-index.json", [])
            if row.get("project") == project
        }

    # baseline projects present
    api_before = project_paths("common-api")
    task_before = project_paths("task-service")
    assert api_before and task_before

    # refresh api, then task-service (non-overlapping)
    reindex_workspace(config, store, projects=["common-api"])
    reindex_workspace(config, store, projects=["task-service"])

    api_after = project_paths("common-api")
    task_after = project_paths("task-service")
    # both slices still present — no project was dropped by the other refresh
    assert api_after == api_before
    assert task_after == task_before


def test_publish_failure_rolls_back_staged_merge(demo_workspace_indexed, monkeypatch):
    from memory_center.core.indexing import reindex as reindex_module
    from memory_center.core.indexing.control_plane import index_control_status

    store = WorkspaceStore(demo_workspace_indexed)
    previous = index_control_status(store)["active_generation"]
    original = WorkspaceStore.publish_generation_payloads

    def crashing_publish(self, payloads, *, publication=None):
        raise RuntimeError("injected publish failure")

    monkeypatch.setattr(WorkspaceStore, "publish_generation_payloads", crashing_publish)
    try:
        with pytest.raises(RuntimeError):
            reindex_module.reindex_workspace(load_workspace_config(demo_workspace_indexed), store)
    finally:
        monkeypatch.setattr(WorkspaceStore, "publish_generation_payloads", original)
    # Previous active pointer and intermediates remain authoritative.
    assert index_control_status(store)["active_generation"] == previous
