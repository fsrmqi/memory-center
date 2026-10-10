from __future__ import annotations

from pathlib import Path

import pytest

from memory_center.core.knowledge.communities import analyze_architecture_communities, architecture_communities_status


def test_architecture_communities_are_explicit_bounded_and_cached(tmp_path: Path) -> None:
    from tests.fixtures import setup_demo_workspace

    workspace = setup_demo_workspace(tmp_path)
    result = analyze_architecture_communities(workspace, limit=999)

    assert result["mode"] == "explicit_offline_aggregate"
    assert result["limits"]["central_nodes"] == 50
    assert "不加载完整图" in result["evidence_boundary"]
    assert architecture_communities_status(workspace)["kind"] == "architecture_communities"


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_architecture_communities_share_cli_http_and_mcp_entrypoints(tmp_path: Path) -> None:
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")
