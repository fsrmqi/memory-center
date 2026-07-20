from __future__ import annotations

from memory_center.core.knowledge.benchmark import evaluate_ontology_hot_path


def test_ontology_hot_path_gate_is_bounded(tmp_path):
    workspace = tmp_path / "workspace.yaml"
    workspace.write_text("workspace: demo\nservices: []\n", encoding="utf-8")
    result = evaluate_ontology_hot_path(str(workspace), samples=3, budget_ms=1000)
    assert result["samples"] == 3
    assert result["passed"] is True
    assert result["scope"].startswith("SQLite aggregate")
