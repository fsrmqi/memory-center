from __future__ import annotations

from memory_center.core.knowledge.aliases import record_identity_alias, resolve_canonical_identity
from memory_center.core.knowledge.assertions import (
    ASSERTION_INDEX_FILE,
    inspect_assertion,
    materialize_static_assertions,
    query_assertions,
    update_assertion_status,
)
from memory_center.core.knowledge.governance import project_session_validation
from memory_center.core.knowledge.migration import migrate_ontology
from memory_center.core.knowledge.state import attach_knowledge_state
from memory_center.core.orchestrator.query import memory_query
from memory_center.core.presentation.evidence_subgraph import export_evidence_subgraph
from memory_center.core.storage.graph import GraphEdge, GraphNode, GraphStore
from memory_center.core.storage.workspace import WorkspaceStore


def test_materialize_static_assertions_keeps_history_and_active_read_model(tmp_path):
    workspace_file = tmp_path / "workspace.yaml"
    workspace_file.write_text("workspace: demo\nservices: []\n", encoding="utf-8")
    store = WorkspaceStore(workspace_file)
    with GraphStore(store.graph_db_path) as graph:
        graph.rebuild(
        [GraphNode("Class:A", "Class", "A", file_path="src/A.java"), GraphNode("Endpoint:/a", "Endpoint", "/a", file_path="src/A.java")],
            [GraphEdge("EXPOSES_ENDPOINT:Class:A->Endpoint:/a", "Class:A", "Endpoint:/a", "EXPOSES_ENDPOINT")],
        )

    first = materialize_static_assertions(store, "gen-1", batch_size=1)
    second = materialize_static_assertions(store, "gen-2", batch_size=1)

    assert first["written"] == 1
    assert second["active"] == 1
    records = store.read_jsonl("assertions.jsonl", limit=10)
    assert len(records) == 2
    assert records[-1]["evidence_level"] == "EXTRACTED"
    summary = store.read_json(ASSERTION_INDEX_FILE, {})
    assert summary["generation"] == "gen-2"
    assert summary["active"] == 1
    exported = export_evidence_subgraph(workspace_file, "Class:A")
    assert exported["edges"][0]["assertion_ref"] == records[-1]["assertion_id"]
    assert len(query_assertions(store, as_of_generation="gen-1")) == 1
    assert len(query_assertions(store, limit=1)) == 1
    assert store.memory_backend().mark_assertions_stale(["src/A.java"]) == 1
    assert query_assertions(store, limit=1)[0]["status"] == "STALE"
    changed = update_assertion_status(store, records[-1]["assertion_id"], status="VERIFIED", verification_ref="validation:test-1")
    assert changed["updated"] is True
    assert query_assertions(store, limit=1)[0]["status"] == "VERIFIED"
    exported = export_evidence_subgraph(workspace_file, "Class:A")
    assert exported["conclusion_cards"][0]["status"] == "VERIFIED"


def test_identity_aliases_keep_historical_ids_and_detect_cycles(tmp_path):
    workspace_file = tmp_path / "workspace.yaml"
    workspace_file.write_text("workspace: demo\nservices: []\n", encoding="utf-8")
    store = WorkspaceStore(workspace_file)
    record_identity_alias(store, alias_id="Class:Old", canonical_id="Class:New", evidence_ref="git:abc")
    assert resolve_canonical_identity(store, "Class:Old")["canonical_id"] == "Class:New"
    record_identity_alias(store, alias_id="Class:New", canonical_id="Class:Old")
    assert resolve_canonical_identity(store, "Class:Old")["ambiguous"] is True


def test_partial_materialization_only_replaces_scoped_assertions(tmp_path):
    workspace_file = tmp_path / "workspace.yaml"
    workspace_file.write_text("workspace: demo\nservices: []\n", encoding="utf-8")
    store = WorkspaceStore(workspace_file)
    with GraphStore(store.graph_db_path) as graph:
        graph.rebuild(
            [
                GraphNode("Class:A", "Class", "A", project="api", file_path="src/A.java"),
                GraphNode("Endpoint:A", "Endpoint", "A", project="api", file_path="src/A.java"),
                GraphNode("Class:B", "Class", "B", project="other", file_path="src/B.java"),
                GraphNode("Endpoint:B", "Endpoint", "B", project="other", file_path="src/B.java"),
            ],
            [
                GraphEdge("edge-a", "Class:A", "Endpoint:A", "EXPOSES_ENDPOINT"),
                GraphEdge("edge-b", "Class:B", "Endpoint:B", "EXPOSES_ENDPOINT"),
            ],
        )
    materialize_static_assertions(store, "gen-1")
    old_b = next(item for item in query_assertions(store, as_of_generation="gen-1", limit=10) if item["subject_id"] == "Class:B")
    update_assertion_status(store, old_b["assertion_id"], status="VERIFIED", verification_ref="validation:b")

    result = materialize_static_assertions(store, "gen-2", paths=["src/A.java"])
    active = query_assertions(store, limit=10)

    assert result["mode"] == "partial"
    assert result["written"] == 1
    assert next(item for item in active if item["subject_id"] == "Class:B")["status"] == "VERIFIED"
    assert next(item for item in active if item["subject_id"] == "Class:B")["generation"] == "gen-1"


def test_closed_assertion_retention_never_removes_active_facts(tmp_path):
    workspace_file = tmp_path / "workspace.yaml"
    workspace_file.write_text("workspace: demo\nservices: []\n", encoding="utf-8")
    store = WorkspaceStore(workspace_file)
    with GraphStore(store.graph_db_path) as graph:
        graph.rebuild([GraphNode("Class:A", "Class", "A"), GraphNode("Endpoint:A", "Endpoint", "A")], [GraphEdge("edge", "Class:A", "Endpoint:A", "EXPOSES_ENDPOINT")])
    materialize_static_assertions(store, "gen-1")
    materialize_static_assertions(store, "gen-2")
    result = store.memory_backend().prune_closed_assertions(valid_before="9999-01-01T00:00:00+00:00", max_closed=0)
    assert result["expired"] == 1
    assert len(query_assertions(store, limit=10)) == 1


def test_assertion_temporal_fields_migration_and_negative_state(tmp_path):
    workspace_file = tmp_path / "workspace.yaml"
    workspace_file.write_text("workspace: demo\nservices: []\n", encoding="utf-8")
    store = WorkspaceStore(workspace_file)
    with GraphStore(store.graph_db_path) as graph:
        graph.rebuild([GraphNode("Class:A", "Class", "A", file_path="src/A.java"), GraphNode("Endpoint:A", "Endpoint", "A", file_path="src/A.java")], [GraphEdge("edge-a", "Class:A", "Endpoint:A", "EXPOSES_ENDPOINT")])
    materialize_static_assertions(store, "gen-1")
    item = query_assertions(store, as_of_time="9999-01-01T00:00:00+00:00", time_axis="observed", limit=500)[0]
    assert item["event_at"] and item["observed_at"] and item["provenance_kind"] == "STATIC"
    assert migrate_ontology(store)["pending_backfill"] == 0
    store.write_json("index-summary.json", {"files": 1})
    payload = attach_knowledge_state(store, {"results": []}, query="missing", mode="test")
    assert payload["knowledge_state"]["state"] == "NOT_FOUND"


def test_session_validation_governance_never_keeps_raw_command(tmp_path):
    workspace_file = tmp_path / "workspace.yaml"
    workspace_file.write_text("workspace: demo\nservices: []\n", encoding="utf-8")
    store = WorkspaceStore(workspace_file)
    result = project_session_validation(
        store,
        "session-1",
        {"status": "passed", "verified": True, "summary": "token=private", "command": "pytest --secret"},
    )
    row = store.read_jsonl("governance-assertions.jsonl", limit=1)[0]
    assert result["projected"] == 1
    assert row["status"] == "VERIFIED"
    assert "private" not in str(row)
    assert "pytest" not in str(row)


def test_default_query_adds_bounded_assertion_summary(tmp_path):
    from tests.fixtures import setup_demo_workspace

    workspace = setup_demo_workspace(tmp_path)
    result = memory_query(workspace, "ArticleFeignClient", limit=3)
    assert result["assertion_summary"]["active"] >= 0
    assert result["assertion_summary"]["next_action"]


def test_admin_assertion_status_requires_evidence_for_verified(tmp_path):
    from memory_center.application.admin import build_admin_registry
    from memory_center.http.route_dispatch import build_http_route_registry
    from memory_center.http.routes.params import RouteParams

    workspace_file = tmp_path / "workspace.yaml"
    workspace_file.write_text("workspace: demo\nservices: []\n", encoding="utf-8")
    store = WorkspaceStore(workspace_file)
    with GraphStore(store.graph_db_path) as graph:
        graph.rebuild([GraphNode("Class:A", "Class", "A"), GraphNode("Endpoint:/a", "Endpoint", "/a")], [GraphEdge("edge", "Class:A", "Endpoint:/a", "EXPOSES_ENDPOINT")])
    materialize_static_assertions(store, "gen-1")
    assertion_id = store.read_json(ASSERTION_INDEX_FILE, {})["recent"][0]["assertion_id"]
    registry = build_admin_registry(workspace_file=str(workspace_file), record_id=assertion_id, status="VERIFIED", payload='{"verification_ref":"validation:test"}')
    assert registry.dispatch("assertion_status")["updated"] is True
    http = build_http_route_registry().dispatch(
        "/workspace/assertion-status",
        RouteParams(
            {"workspace": [str(workspace_file)], "assertion_id": [assertion_id], "status": ["REJECTED"]},
            str(workspace_file),
        ),
    )
    assert http["updated"] is True
    inspected = inspect_assertion(store, assertion_id)
    assert inspected["found"] is True
    assert inspected["assertion"]["status"] == "REJECTED"
