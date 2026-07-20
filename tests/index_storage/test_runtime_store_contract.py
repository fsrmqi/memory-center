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
