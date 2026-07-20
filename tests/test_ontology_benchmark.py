from __future__ import annotations

from memory_center.core.knowledge.benchmark import evaluate_assertion_scope_gate, evaluate_ontology_hot_path
from memory_center.core.storage.graph import GraphEdge, GraphNode, GraphStore
from memory_center.core.storage.workspace import WorkspaceStore


def test_ontology_hot_path_gate_is_bounded(tmp_path):
    workspace = tmp_path / "workspace.yaml"
    workspace.write_text("workspace: demo\nservices: []\n", encoding="utf-8")
    result = evaluate_ontology_hot_path(str(workspace), samples=3, budget_ms=1000)
    assert result["samples"] == 3
    assert result["passed"] is True
    assert result["scope"].startswith("SQLite aggregate")


def test_assertion_scope_gate_is_read_only_and_bounded(tmp_path):
    workspace = tmp_path / "workspace.yaml"
    workspace.write_text("workspace: demo\nservices: []\n", encoding="utf-8")
    store = WorkspaceStore(workspace)
    with GraphStore(store.graph_db_path) as graph:
        graph.rebuild(
            [
                GraphNode("Class:A", "Class", "A", file_path="src/A.java"),
                GraphNode("Endpoint:A", "Endpoint", "A", file_path="src/A.java"),
                GraphNode("Class:B", "Class", "B", file_path="src/B.java"),
                GraphNode("Endpoint:B", "Endpoint", "B", file_path="src/B.java"),
            ],
            [GraphEdge("a", "Class:A", "Endpoint:A", "EXPOSES_ENDPOINT"), GraphEdge("b", "Class:B", "Endpoint:B", "EXPOSES_ENDPOINT")],
        )
    result = evaluate_assertion_scope_gate(str(workspace), paths=["src/A.java"])
    assert result["read_only"] is True
    assert result["selected_assertion_edges"] == 1
    assert result["passed"] is True
