from __future__ import annotations

import sqlite3

import pytest

from memory_center.core.storage.graph import GraphEdge, GraphNode
from memory_center.core.storage.maintenance import (
    cleanup_legacy_memory_store,
    compact_semantic_runtime_state,
    sparsify_static_assertions,
)
from memory_center.core.storage.runtime import RuntimeStore
from memory_center.core.storage.workspace import WorkspaceStore


def test_delivery_receipt_projection_upgrades_and_streams_legacy_rows(tmp_path) -> None:
    db_path = tmp_path / "graph.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE delivery_receipt_sync(
              task_id TEXT PRIMARY KEY,
              source_size INTEGER NOT NULL DEFAULT 0,
              source_mtime_ns INTEGER NOT NULL DEFAULT 0,
              synced_at TEXT DEFAULT ''
            )
            """
        )
        conn.execute("INSERT INTO delivery_receipt_sync VALUES('legacy-task', 12, 34, 'old')")

    consumed = 0

    def receipts():
        nonlocal consumed
        for index in range(1201):
            consumed += 1
            receipt_id = f"receipt-{index}"
            yield {
                "receipt_id": receipt_id,
                "status": "passed",
                "evidence_kind": "manual_verified",
                "acceptance_ids": ["AC-1"],
                "evidence_refs": [f"delivery-validation:task-ref:{receipt_id}"],
            }

    with RuntimeStore(db_path) as store:
        assert store.delivery_receipt_sync_state("legacy-task")["projection_version"] == 0
        store.replace_delivery_receipts(
            "task",
            receipts(),
            source_size=100,
            source_mtime_ns=200,
            synced_at="now",
        )
        state = store.delivery_receipt_sync_state("task")
        candidates = store.delivery_verified_acceptance_candidates("task", "task-ref")

    assert consumed == 1201
    assert state == {"source_size": 100, "source_mtime_ns": 200, "projection_version": 2}
    assert candidates == [{"acceptance_id": "AC-1", "receipt_id": "", "evidence_kind": "manual_verified"}]


def test_runtime_store_unifies_graph_and_runtime_records(tmp_path) -> None:
    """图事实和运行记录必须落在同一 SQLite 实例，不能再分裂为两个 store。"""
    with RuntimeStore(tmp_path / "graph.db") as store:
        store.bulk_write(
            [GraphNode("Method:source", "Method", "source"), GraphNode("Method:target", "Method", "target")],
            [GraphEdge("CALLS:source-target", "Method:source", "Method:target", "CALLS_METHOD")],
        )
        store.append_record("session-events.jsonl", {"type": "tool_call"}, record_id="event-1")

        assert store.neighbors("Method:source", direction="downstream", max_depth=1)[0]["id"] == "Method:target"
        assert store.traverse_edges("Method:source", direction="downstream", max_depth=1)[0]["id"] == "CALLS:source-target"
        assert store.query_records(collection="session-events.jsonl")["records"][0]["record_id"] == "event-1"


def test_runtime_store_transaction_rolls_back_and_propagates_write_failure(tmp_path) -> None:
    with RuntimeStore(tmp_path / "graph.db") as store:
        with pytest.raises(RuntimeError, match="write failed"):
            with store.pool.transaction() as conn:
                conn.execute("INSERT INTO refs(ref_path, payload_json) VALUES(?, ?)", ("broken", "{}"))
                raise RuntimeError("write failed")

        assert store.query_refs(ref_path="broken")["refs"] == []


def test_runtime_neighbors_uses_bounded_bfs_for_wide_cyclic_graph(tmp_path) -> None:
    """高分支且有回边时，节点遍历仍应有界、去重并排除起点。"""
    fanout = 256
    nodes = [GraphNode("root", "Method", "root")]
    nodes.extend(GraphNode(f"n{index:03d}", "Method", f"n{index:03d}") for index in range(fanout))
    edges = [GraphEdge(f"out-{index}", "root", f"n{index:03d}", "CALLS_METHOD") for index in range(fanout)]
    edges.extend(GraphEdge(f"back-{index}", f"n{index:03d}", "root", "CALLS_METHOD") for index in range(fanout))

    with RuntimeStore(tmp_path / "graph.db") as store:
        store.rebuild(nodes, edges)
        results = store.neighbors("root", direction="both", max_depth=4, limit=20, edge_types=["CALLS_METHOD"])

    assert len(results) == 20
    assert len({item["id"] for item in results}) == 20
    assert all(item["id"] != "root" and item["depth"] == 1 for item in results)


def test_legacy_memory_store_cleanup_never_targets_runtime_db(tmp_path) -> None:
    workspace = tmp_path / ".memory-center" / "workspace.yaml"
    workspace.parent.mkdir(parents=True)
    workspace.write_text("workspace: demo\nservices: []\n", encoding="utf-8")
    legacy = workspace.parent / "memory" / "memory.db"
    legacy.parent.mkdir()
    legacy.write_bytes(b"retired-store")

    preview = cleanup_legacy_memory_store(workspace)
    assert preview["bytes"] == len(b"retired-store")
    assert legacy.exists()
    result = cleanup_legacy_memory_store(workspace, apply=True)
    assert result["removed"]
    assert not legacy.exists()
    assert (workspace.parent / "graph" / "graph.db").exists() is False


def test_assertion_sparsify_removes_legacy_static_rows_from_both_mirrors(tmp_path) -> None:
    workspace = tmp_path / ".memory-center" / "workspace.yaml"
    workspace.parent.mkdir(parents=True)
    workspace.write_text("workspace: demo\nservices: []\n", encoding="utf-8")
    store = RuntimeStore(workspace.parent / "graph" / "graph.db")
    try:
        static = {
            "assertion_id": "static:edge-1",
            "subject_id": "Class:demo:Source",
            "predicate": "CALLS_METHOD",
            "object_id": "Method:demo:Target",
            "status": "EXTRACTED",
            "generation": "gen-1",
            "valid_from": "2026-01-01T00:00:00Z",
            "provenance_kind": "STATIC",
            "relation_mode": "STRUCTURAL",
        }
        store.upsert_assertions([static])
        store.append_record("assertions.jsonl", {**static, "type": "static_assertion"})
        store.upsert_assertions([{**static, "assertion_id": "manual:1", "provenance_kind": "MANUAL", "relation_mode": "GOVERNANCE"}])
    finally:
        store.close()

    preview = sparsify_static_assertions(workspace)
    assert preview["static_assertion_rows"] == 1
    assert preview["static_json_rows"] == 1
    result = sparsify_static_assertions(workspace, apply=True)
    assert result["deleted_assertion_rows"] == 1
    assert result["deleted_json_rows"] == 1
    with RuntimeStore(workspace.parent / "graph" / "graph.db") as verify:
        assert verify.assertion_by_id("static:edge-1") is None
        assert verify.assertion_by_id("manual:1") is not None
        assert verify.query_records(collection="assertions.jsonl")["records"] == []


def test_semantic_compaction_removes_duplicated_document_payload(tmp_path) -> None:
    workspace = tmp_path / ".memory-center" / "workspace.yaml"
    workspace.parent.mkdir(parents=True)
    workspace.write_text("workspace: demo\nservices: []\n", encoding="utf-8")
    store = WorkspaceStore(workspace)
    store.write_json("semantic-node-index.json", {
        "version": 4, "node_count": 1, "doc_count": 1, "docs": [{"node_id": "n1", "dense_vector": [0.1]}],
        "df": {"demo": 1}, "avgdl": 3.0,
    })

    preview = compact_semantic_runtime_state(workspace)
    assert preview["changed"] is True
    assert set(preview["removed_fields"]) == {"avgdl", "df", "docs"}

    result = compact_semantic_runtime_state(workspace, apply=True)
    persisted = store.read_json_prefer_backend("semantic-node-index.json", {})
    assert result["changed"] is True
    assert persisted["storage_mode"] == "runtime_indexes_v1"
    assert "docs" not in persisted
