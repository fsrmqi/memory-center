from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from memory_center.cli.main import app
from memory_center.core.indexing.precision import tree_sitter_activation_status
from memory_center.core.orchestrator.resume import workspace_next_actions


def test_tree_sitter_activation_status_exposes_install_and_validation_commands() -> None:
    status = tree_sitter_activation_status()

    assert status["extra"] == "ast"
    assert status["install_commands"]["pipx"] == (
        'pipx inject memory-center "tree-sitter>=0.25,<0.26" "tree-sitter-java>=0.23,<0.24"'
    )
    assert status["install_commands"]["local"] == (
        'python -m pip install "tree-sitter>=0.25,<0.26" "tree-sitter-java>=0.23,<0.24"'
    )
    assert "memory-center eval-parser-benchmark" in status["validation_command"]
    assert status["recommended_action"] in {
        "use_tree_sitter_parser",
        "install_tree_sitter_java_and_reindex",
        "fix_tree_sitter_initialization",
    }


def test_workspace_next_actions_include_evidence_backed_action_items(demo_workspace: Path) -> None:
    result = workspace_next_actions(demo_workspace, intent="梳理 Java 全链路", limit=3)

    assert result["actions"]
    assert result["action_items"]
    first = result["action_items"][0]
    assert {"action", "reason", "evidence", "priority", "command"}.issubset(first)
    assert first["action"] == result["actions"][0]
    assert first["reason"]
    assert first["evidence"]


def test_parser_status_cli_reports_activation_status() -> None:
    result = CliRunner().invoke(app, ["parser-status"])

    assert result.exit_code == 0
    assert "recommended_action" in result.stdout
    assert "install_commands" in result.stdout
