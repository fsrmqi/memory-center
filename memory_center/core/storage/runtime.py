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
        """按层返回邻居节点，避免递归 CTE 在高分支图中物化路径组合。

        每一层只查询当前 frontier，并在进入下一层前按节点 ID 去重。这样
        复杂度受 ``max_depth``、``limit`` 和有界候选数约束；环状调用图不会
        因为相同节点的不同路径而重复膨胀。关系边遍历仍须显式使用
        :meth:`traverse_edges`。
        """
        if not node_id or limit <= 0 or max_depth <= 0:
            return []

        normalized_direction = {"outgoing": "downstream", "incoming": "upstream"}.get(direction, direction)
        directions = ("downstream", "upstream") if normalized_direction == "both" else (normalized_direction,)
        if not set(directions).issubset({"downstream", "upstream"}):
            directions = ("downstream",)

        seen = {node_id}
        frontier = [node_id]
        discovered: list[tuple[str, int]] = []
        type_values = sorted({str(edge_type) for edge_type in edge_types or [] if edge_type})

        with self.connect() as conn:
            for depth in range(1, max_depth + 1):
                if not frontier or len(discovered) >= limit:
                    break
                placeholders = ",".join("?" for _ in frontier)
                candidate_limit = min(4096, max(128, (limit - len(discovered)) * 8))
                next_frontier: list[str] = []

                for traversal_direction in directions:
                    source_column, target_column = (
                        ("source_id", "target_id")
                        if traversal_direction == "downstream"
                        else ("target_id", "source_id")
                    )
                    filters = ""
                    params: list[Any] = [*frontier]
                    if type_values:
                        type_placeholders = ",".join("?" for _ in type_values)
                        filters = f" AND type IN ({type_placeholders})"
                        params.extend(type_values)
                    params.append(candidate_limit)
                    rows = conn.execute(
                        f"""
                        SELECT DISTINCT {target_column} AS neighbor_id
                        FROM edges
                        WHERE {source_column} IN ({placeholders}){filters}
                        ORDER BY {target_column}
                        LIMIT ?
                        """,
                        params,
                    ).fetchall()
                    for row in rows:
                        neighbor_id = str(row["neighbor_id"])
                        if neighbor_id in seen:
                            continue
                        seen.add(neighbor_id)
                        next_frontier.append(neighbor_id)
                        discovered.append((neighbor_id, depth))
                        if len(discovered) >= limit:
                            break
                    if len(discovered) >= limit:
                        break
                frontier = next_frontier

            if not discovered:
                return []
            ids = [item[0] for item in discovered]
            placeholders = ",".join("?" for _ in ids)
            rows = conn.execute(f"SELECT * FROM nodes WHERE id IN ({placeholders})", ids).fetchall()

        rows_by_id = {str(row["id"]): row for row in rows}
        result = []
        for neighbor_id, depth in discovered:
            row = rows_by_id.get(neighbor_id)
            if row is not None:
                result.append({**dict(row), "metadata": _decode_metadata(row["metadata_json"]), "depth": depth})
        return result

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

    def traverse_edges_batch(self, node_ids: list[str], *, direction: str = "both", limit_per_node: int = 10) -> dict[str, list[dict[str, Any]]]:
        """一次读取多个节点的一跳边，供 Context Pack 避免 N 次 SQLite 往返。"""
        ids = list(dict.fromkeys(str(node_id) for node_id in node_ids if node_id))[:32]
        if not ids:
            return {}
        limit = max(1, min(int(limit_per_node), 100))
        placeholders = ",".join("?" for _ in ids)
        clauses: list[str] = []
        params: list[Any] = []
        if direction in {"both", "downstream"}:
            clauses.append(f"source_id IN ({placeholders})")
            params.extend(ids)
        if direction in {"both", "upstream"}:
            clauses.append(f"target_id IN ({placeholders})")
            params.extend(ids)
        with self.connect() as conn:
            rows = conn.execute(f"SELECT * FROM edges WHERE {' OR '.join(clauses)} ORDER BY id", params).fetchall()
        result = {node_id: [] for node_id in ids}
        for row in rows:
            edge = dict(row)
            for node_id in (edge.get("source_id"), edge.get("target_id")):
                if node_id in result and len(result[node_id]) < limit:
                    result[node_id].append(edge)
        return result

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
