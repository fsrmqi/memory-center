from __future__ import annotations

from pathlib import Path


def test_explicit_performance_snapshot_records_aggregate_only_metrics(monkeypatch, tmp_path: Path) -> None:
    import memory_center.application.performance as performance_module
    from memory_center.application.performance import record_workspace_performance_snapshot
    from memory_center.core.retrieval.planner import workspace_performance_snapshot_status
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    monkeypatch.setattr(performance_module, "memory_query_hybrid", lambda *_args, **_kwargs: {"ok": True})

    first = record_workspace_performance_snapshot(workspace, samples=2)
    second = record_workspace_performance_snapshot(workspace, samples=2)
    status = workspace_performance_snapshot_status(workspace)

    assert first["snapshot"]["samples"] == 2
    assert first["snapshot"]["outcomes"] == {"ok": 2, "error": 0}
    assert "query" not in first["snapshot"]
    assert second["trend"]["samples"] == 2
    assert status["status"] == "healthy"
    assert len(status["snapshots"]) == 2


def test_http_route_contract_audit_covers_registry_and_post_only_writes() -> None:
    from memory_center.http.route_dispatch import audit_http_route_contract, http_route_spec, is_mutating_http_route

    report = audit_http_route_contract()

    assert report["passed"] is True
    assert http_route_spec("/workspace/performance-status").methods == frozenset({"GET"})
    assert is_mutating_http_route("/workspace/performance-snapshot") is True
    assert is_mutating_http_route("/workspace/job-cancel") is True
    assert is_mutating_http_route("/workspace/task-space/resolve") is False
