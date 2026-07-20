"""唯一的 SQLite 运行时存储。

``RuntimeStore`` 合并代码图、索引元数据、运行记录、引用和断言读模型，
统一使用同一个 ``graph.db`` 连接与 schema。它是 core 层唯一允许注入的
SQLite 存储类型。
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from .graph import GraphEdge, GraphNode, _GraphOperations
from .memory_backend import _MemoryRecordOperations


class _RuntimeConnection:
    """为向量、倒排和推理组件提供统一的连接/事务接口。"""

    def __init__(self, store: RuntimeStore):
        self._store = store

    @contextmanager
    def connection(self) -> Iterator[Any]:
        yield self._store.connect()

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        conn = self._store.connect()
        try:
            yield conn
            conn.commit()
        except BaseException:
            # 写事务必须回滚并继续传播，不能把索引损坏伪装为可降级结果。
            conn.rollback()
            raise

    def close(self) -> None:
        self._store.close()


class RuntimeStore(_GraphOperations, _MemoryRecordOperations):
    """Memory Center 唯一的 SQLite 访问层。"""

    def __init__(self, db_path: str, pool_size: int = 4):
        del pool_size  # API 保持简单；单实例连接由 WorkspaceStore 生命周期管理。
        super().__init__(db_path)
        self.pool = _RuntimeConnection(self)

    def _init_schema(self) -> None:
        _GraphOperations._init_schema(self)
        _MemoryRecordOperations._init_schema(self)

    def upsert_nodes(self, rows: list[tuple]) -> None:
        self.bulk_write(
            [GraphNode(*row[:6], _decode_metadata(row[6] if len(row) > 6 else {})) for row in rows],
            [],
        )

    def upsert_edges(self, rows: list[tuple]) -> None:
        self.bulk_write(
            [],
            [GraphEdge(*row[:5], _decode_metadata(row[5] if len(row) > 5 else {})) for row in rows],
        )

    def graph_counts(self) -> dict[str, int]:
        counts = self.counts()
        return {"nodes": int(counts.get("nodes", 0)), "edges": int(counts.get("edges", 0))}

    def neighbors(
        self,
        node_id: str,
        direction: str = "both",
        max_depth: int = 2,
        limit: int = 200,
        edge_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """返回邻居节点；关系遍历必须显式使用 ``traverse_edges``。"""
        if direction == "downstream":
            join_condition = "edge.source_id = chain.node_id"
        elif direction == "upstream":
            join_condition = "edge.target_id = chain.node_id"
        else:
            join_condition = "(edge.source_id = chain.node_id OR edge.target_id = chain.node_id)"
        filters = ""
        params: list[Any] = [node_id, max_depth]
        if edge_types:
            filters = f" AND edge.type IN ({','.join('?' for _ in edge_types)})"
            params.extend(edge_types)
        params.extend([node_id, limit])
        sql = f"""
        WITH RECURSIVE chain(node_id, depth) AS (
            SELECT ?, 0
            UNION
            SELECT CASE WHEN edge.source_id = chain.node_id THEN edge.target_id ELSE edge.source_id END,
                   chain.depth + 1
            FROM edges edge JOIN chain ON {join_condition}
            WHERE chain.depth < ?{filters}
              AND CASE WHEN edge.source_id = chain.node_id THEN edge.target_id ELSE edge.source_id END <> ?
        )
        SELECT DISTINCT node.*, chain.depth FROM chain JOIN nodes node ON node.id = chain.node_id
        WHERE chain.node_id <> ? ORDER BY chain.depth LIMIT ?
        """
        # The start-node predicate appears in both the recursive and final clauses.
        params.insert(-1, node_id)
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            {**dict(row), "metadata": _decode_metadata(row["metadata_json"])}
            for row in rows
        ]

    def edges_for_node(self, node_id: str, direction: str = "both", limit: int = 200) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if direction == "upstream":
                rows = conn.execute("SELECT * FROM edges WHERE target_id=? LIMIT ?", (node_id, limit)).fetchall()
            elif direction == "downstream":
                rows = conn.execute("SELECT * FROM edges WHERE source_id=? LIMIT ?", (node_id, limit)).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM edges WHERE source_id=? OR target_id=? LIMIT ?",
                    (node_id, node_id, limit),
                ).fetchall()
        return [dict(row) for row in rows]

    def traverse_edges(
        self,
        node_id: str,
        direction: str = "both",
        max_depth: int = 2,
        limit: int = 200,
        edge_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """按关系边遍历图，供影响分析和证据子图等边导向场景使用。"""
        return _GraphOperations.neighbors(self, node_id, direction, max_depth, limit, edge_types)

    def clear_graph(self) -> None:
        self.clear()

    def remove_nodes_by_scope(self, project_filter: set[str], path_filters: list[str]) -> set[str]:
        return self.remove_by_scope(project_filter, path_filters)

    def memory_stats(self) -> dict[str, Any]:
        return self.stats()


def _decode_metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    import json

    try:
        decoded = json.loads(str(value))
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}
