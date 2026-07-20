from __future__ import annotations

import pytest

from memory_center.core.storage.graph import GraphEdge, GraphNode
from memory_center.core.storage.runtime import RuntimeStore


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
