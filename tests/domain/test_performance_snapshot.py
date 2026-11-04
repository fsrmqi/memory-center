from __future__ import annotations

from pathlib import Path

import pytest


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


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_http_route_contract_audit_covers_registry_and_post_only_writes() -> None:
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_scoped_refresh_performance_is_aggregate_and_shared_by_entrypoints(tmp_path: Path) -> None:
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")
