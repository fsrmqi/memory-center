from __future__ import annotations

import pytest

from memory_center.core.knowledge.aliases import record_identity_alias, resolve_canonical_identity
from memory_center.core.knowledge.assertions import (
    ASSERTION_INDEX_FILE,
    materialize_static_assertions,
    query_assertions,
    update_assertion_status,
)
from memory_center.core.knowledge.governance import (
    GOVERNANCE_ENTITIES_FILE,
    project_session_validation,
    record_actions,
)
from memory_center.core.knowledge.state import attach_knowledge_state
from memory_center.core.orchestrator.query import memory_query_hybrid
from memory_center.core.presentation.evidence_subgraph import export_evidence_subgraph
from memory_center.core.storage.graph import GraphEdge, GraphNode
from memory_center.core.storage.runtime import RuntimeStore
from memory_center.core.storage.workspace import WorkspaceStore


def test_static_assertions_are_derived_and_status_is_sparse_override(tmp_path):
    workspace_file = tmp_path / "workspace.yaml"
    workspace_file.write_text("workspace: demo\nservices: []\n", encoding="utf-8")
    store = WorkspaceStore(workspace_file)
    with RuntimeStore(store.graph_db_path) as graph:
        graph.rebuild(
        [GraphNode("Class:A", "Class", "A", file_path="src/A.java"), GraphNode("Endpoint:/a", "Endpoint", "/a", file_path="src/A.java")],
            [GraphEdge("EXPOSES_ENDPOINT:Class:A->Endpoint:/a", "Class:A", "Endpoint:/a", "EXPOSES_ENDPOINT")],
        )

    first = materialize_static_assertions(store, "gen-1", batch_size=1)
    second = materialize_static_assertions(store, "gen-2", batch_size=1)

    assert first["written"] == 0
    assert second["active"] == 1
    summary = store.read_json(ASSERTION_INDEX_FILE, {})
    assert summary["generation"] == "gen-2"
    assert summary["active"] == 1
    exported = export_evidence_subgraph(workspace_file, "Class:A")
    assertion_id = exported["edges"][0]["assertion_ref"]
    assert assertion_id.startswith("static:")
    assert query_assertions(store, limit=1)[0]["status"] == "EXTRACTED"
    changed = update_assertion_status(store, assertion_id, status="VERIFIED", verification_ref="validation:test-1")
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


def test_repeated_query_actions_reuse_stable_ids_without_duplicate_writes(tmp_path):
    workspace_file = tmp_path / "workspace.yaml"
    workspace_file.write_text("workspace: demo\nservices: []\n", encoding="utf-8")
    store = WorkspaceStore(workspace_file)
    actions = [{"action": "inspect_top_result", "command": "memory-center symbol --name OrderService"}]

    first = record_actions(store, origin="memory_query_hybrid:OrderService", actions=actions)
    second = record_actions(store, origin="memory_query_hybrid:OrderService", actions=actions)

    rows = store.read_jsonl(GOVERNANCE_ENTITIES_FILE)
    assert first[0]["action_id"] == second[0]["action_id"]
    assert len(rows) == 1


def test_partial_materialization_only_replaces_scoped_assertions(tmp_path):
    workspace_file = tmp_path / "workspace.yaml"
    workspace_file.write_text("workspace: demo\nservices: []\n", encoding="utf-8")
    store = WorkspaceStore(workspace_file)
    with RuntimeStore(store.graph_db_path) as graph:
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
    old_b = next(item for item in query_assertions(store, limit=10) if item["subject_id"] == "Class:B")
    update_assertion_status(store, old_b["assertion_id"], status="VERIFIED", verification_ref="validation:b")

    result = materialize_static_assertions(store, "gen-2", paths=["src/A.java"])
    active = query_assertions(store, limit=10)

    assert result["mode"] == "derived_partial"
    assert result["written"] == 0
    assert next(item for item in active if item["subject_id"] == "Class:B")["status"] == "VERIFIED"
    assert next(item for item in active if item["subject_id"] == "Class:B")["assertion_id"] == old_b["assertion_id"]


def test_derived_static_assertions_do_not_create_closed_history(tmp_path):
    workspace_file = tmp_path / "workspace.yaml"
    workspace_file.write_text("workspace: demo\nservices: []\n", encoding="utf-8")
    store = WorkspaceStore(workspace_file)
    with RuntimeStore(store.graph_db_path) as graph:
        graph.rebuild([GraphNode("Class:A", "Class", "A"), GraphNode("Endpoint:A", "Endpoint", "A")], [GraphEdge("edge", "Class:A", "Endpoint:A", "EXPOSES_ENDPOINT")])
    materialize_static_assertions(store, "gen-1")
    materialize_static_assertions(store, "gen-2")
    result = store.memory_backend().prune_closed_assertions(valid_before="9999-01-01T00:00:00+00:00", max_closed=0)
    assert result["expired"] == 0
    assert len(query_assertions(store, limit=10)) == 1


def test_assertion_temporal_fields_migration_and_negative_state(tmp_path):
    workspace_file = tmp_path / "workspace.yaml"
    workspace_file.write_text("workspace: demo\nservices: []\n", encoding="utf-8")
    store = WorkspaceStore(workspace_file)
    with RuntimeStore(store.graph_db_path) as graph:
        graph.rebuild([GraphNode("Class:A", "Class", "A", file_path="src/A.java"), GraphNode("Endpoint:A", "Endpoint", "A", file_path="src/A.java")], [GraphEdge("edge-a", "Class:A", "Endpoint:A", "EXPOSES_ENDPOINT")])
    materialize_static_assertions(store, "gen-1")
    item = query_assertions(store, as_of_time="9999-01-01T00:00:00+00:00", time_axis="observed", limit=500)[0]
    assert item["event_at"] and item["observed_at"] and item["provenance_kind"] == "STATIC"
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
    result = memory_query_hybrid(workspace, "ArticleFeignClient", limit=3)
    assert result["knowledge_state"]["state"] in {"FOUND", "NOT_FOUND", "NOT_INDEXED", "STALE"}
    assert result["knowledge_state"]["next_action"]
    timings = result["performance"]["timing_ms"]
    assert {"setup", "core_retrieval", "quality_and_actions", "total"} <= set(timings)
    assert all(value >= 0 for value in timings.values())


def test_freshness_uses_published_summary_not_runtime_write_mtime(tmp_path):
    from memory_center.core.freshness.status import IndexFreshnessService

    workspace_file = tmp_path / "workspace.yaml"
    workspace_file.write_text("workspace: demo\nservices: []\n", encoding="utf-8")
    store = WorkspaceStore(workspace_file)
    store.write_json("file-index.json", [{"path": "Demo.java"}])
    store.write_json("graph-summary.json", {"nodes": 1, "edges": 0})

    before = IndexFreshnessService(workspace_file).check()
    store.append_jsonl("operation-events.jsonl", {"operation": "query"})
    after = IndexFreshnessService(workspace_file).check()

    assert before.status == after.status == "fresh"
    assert before.last_indexed_at == after.last_indexed_at


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_admin_assertion_status_requires_evidence_for_verified(tmp_path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")
