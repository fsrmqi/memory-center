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
    assert http_route_spec("/workspace/scoped-refresh-performance").methods == frozenset({"GET"})
    assert is_mutating_http_route("/workspace/performance-snapshot") is True
    assert is_mutating_http_route("/workspace/job-cancel") is True
    assert is_mutating_http_route("/workspace/task-space/resolve") is False


def test_scoped_refresh_performance_is_aggregate_and_shared_by_entrypoints(tmp_path: Path) -> None:
    from memory_center.application.admin import build_admin_registry
    from memory_center.core.retrieval.planner import (
        record_scoped_refresh_performance,
        scoped_refresh_performance_status,
    )
    from memory_center.http.route_dispatch import build_http_route_registry
    from memory_center.http.routes.params import RouteParams
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    recorded = record_scoped_refresh_performance(
        workspace,
        timing_ms={"load_indexes": 20.0, "graph_update": 80.0, "total": 120.0},
        path_count=2,
        project_count=0,
        scanned_files=2,
        generation="gen-test",
    )
    status = scoped_refresh_performance_status(workspace)
    route = build_http_route_registry().dispatch(
        "/workspace/scoped-refresh-performance",
        RouteParams({"workspace": [str(workspace)]}, str(workspace)),
    )
    admin = build_admin_registry(workspace_file=str(workspace)).dispatch("scoped_refresh_performance")

    assert recorded["status"] == "healthy"
    assert status["samples"] == route["samples"] == admin["samples"] == 1
    assert status["latest"]["dominant_stage"] == "graph_update"
    assert "paths" not in status["latest"]
    assert status["latest"]["scope"] == {"path_count": 2, "project_count": 0, "scanned_files": 2}
