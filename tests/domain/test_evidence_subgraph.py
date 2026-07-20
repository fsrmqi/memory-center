from __future__ import annotations

from pathlib import Path

from memory_center.core.presentation.evidence_subgraph import export_evidence_subgraph


def test_evidence_subgraph_is_bounded_and_does_not_include_node_metadata(tmp_path: Path) -> None:
    from tests.fixtures import setup_demo_workspace

    workspace = setup_demo_workspace(tmp_path)
    result = export_evidence_subgraph(workspace, "ArticleFeignClient", max_depth=9, max_edges=999, output_format="markdown")

    assert result["found"] is True
    assert result["limits"] == {"max_depth": 3, "max_edges": 120, "max_nodes": 80}
    assert len(result["nodes"]) <= 80
    assert len(result["edges"]) <= 120
    assert len(result["conclusion_cards"]) <= 20
    assert all("next_action" in card for card in result["conclusion_cards"])
    assert all(card["action"]["stop_condition"] for card in result["conclusion_cards"])
    assert result["governance_assertions"] == []
    assert {edge["evidence_level"] for edge in result["edges"]} <= {"EXTRACTED", "INFERRED", "AMBIGUOUS", "VERIFIED"}
    assert "metadata" not in result["nodes"][0]
    assert "# 证据子图" in result["content"]


def test_evidence_subgraph_http_and_cli_share_exporter(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from memory_center.application.admin import build_admin_registry
    from memory_center.cli.main import app
    from memory_center.http.route_dispatch import build_http_route_registry
    from memory_center.http.routes.params import RouteParams
    from tests.fixtures import setup_demo_workspace

    workspace = setup_demo_workspace(tmp_path)
    http = build_http_route_registry().dispatch(
        "/workspace/evidence-subgraph",
        RouteParams({"workspace": [str(workspace)], "target": ["ArticleFeignClient"]}, str(workspace)),
    )
    mcp = build_admin_registry(workspace_file=str(workspace), text="ArticleFeignClient").dispatch("evidence_subgraph_export")
    cli = CliRunner().invoke(app, ["export-evidence-subgraph", "--workspace", str(workspace), "--target", "ArticleFeignClient"])

    assert http["found"] is True
    assert mcp["found"] is True
    assert cli.exit_code == 0
    assert '"kind": "evidence_subgraph"' in cli.output
