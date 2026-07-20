from __future__ import annotations

from pathlib import Path

from memory_center.core.knowledge.communities import analyze_architecture_communities, architecture_communities_status


def test_architecture_communities_are_explicit_bounded_and_cached(tmp_path: Path) -> None:
    from tests.fixtures import setup_demo_workspace

    workspace = setup_demo_workspace(tmp_path)
    result = analyze_architecture_communities(workspace, limit=999)

    assert result["mode"] == "explicit_offline_aggregate"
    assert result["limits"]["central_nodes"] == 50
    assert "不加载完整图" in result["evidence_boundary"]
    assert architecture_communities_status(workspace)["kind"] == "architecture_communities"


def test_architecture_communities_share_cli_http_and_mcp_entrypoints(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from memory_center.application.admin import build_admin_registry
    from memory_center.cli.main import app
    from memory_center.http.route_dispatch import build_http_route_registry
    from memory_center.http.routes.params import RouteParams
    from tests.fixtures import setup_demo_workspace

    workspace = setup_demo_workspace(tmp_path)
    http = build_http_route_registry().dispatch(
        "/workspace/architecture-communities", RouteParams({"workspace": [str(workspace)]}, str(workspace))
    )
    mcp = build_admin_registry(workspace_file=str(workspace)).dispatch("architecture_communities")
    cli = CliRunner().invoke(app, ["architecture-communities", "--workspace", str(workspace)])

    assert http["kind"] == mcp["kind"] == "architecture_communities"
    assert cli.exit_code == 0
