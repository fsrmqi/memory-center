"""Transitive inference engine — derive implicit relationships from the graph.

E.g., if A calls B and B calls C, infer A transitively calls C.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..storage.runtime import RuntimeStore


@dataclass
class TransitiveRelation:
    source_id: str
    target_id: str
    path: list[str]  # intermediate node IDs
    edge_types: list[str]
    confidence: float


class TransitiveInferenceEngine:
    """Derive transitive relationships using recursive CTEs."""

    def __init__(self, store: RuntimeStore):
        self._store = store

    def find_transitive_calls(
        self,
        source_id: str,
        max_depth: int = 3,
        limit: int = 50,
    ) -> list[TransitiveRelation]:
        """Find bounded shortest transitive call paths.

        A recursive CTE with ``LIMIT`` on the final SELECT still materializes
        every path first, which explodes on large call graphs. This traversal
        batches one SQL read per depth and bounds the frontier before the next
        layer.
        """
        depth_limit = max(1, int(max_depth or 1))
        result_limit = max(1, int(limit or 1))
        frontier_limit = max(32, result_limit * 4)
        frontier = [(source_id, [source_id], [])]
        visited_depth = {source_id: 0}
        results: list[TransitiveRelation] = []

        for depth in range(1, depth_limit + 1):
            if not frontier:
                break
            source_ids = sorted({state[0] for state in frontier})
            placeholders = ",".join("?" for _ in source_ids)
            sql = f"""
                SELECT source_id, target_id, type
                FROM edges
                WHERE source_id IN ({placeholders})
                  AND type IN ('CALLS_METHOD', 'CALLS_SERVICE')
                ORDER BY source_id, type, target_id
                LIMIT ?
            """
            with self._store.pool.connection() as conn:
                rows = conn.execute(
                    sql,
                    [*source_ids, max(1024, frontier_limit * 32)],
                ).fetchall()

            edges_by_source: dict[str, list[Any]] = {}
            for row in rows:
                edges_by_source.setdefault(str(row["source_id"]), []).append(row)

            next_frontier = []
            for current_id, path, edge_types in frontier:
                for row in edges_by_source.get(current_id, []):
                    target_id = str(row["target_id"])
                    if target_id in path:
                        continue
                    next_path = [*path, target_id]
                    next_edge_types = [*edge_types, str(row["type"])]
                    if depth >= 2:
                        confidence = max(0.3, 1.0 - 0.2 * depth)
                        results.append(
                            TransitiveRelation(
                                source_id=source_id,
                                target_id=target_id,
                                path=next_path,
                                edge_types=next_edge_types,
                                confidence=round(confidence, 2),
                            )
                        )
                        if len(results) >= result_limit:
                            return results
                    previous_depth = visited_depth.get(target_id)
                    if previous_depth is None or depth < previous_depth:
                        visited_depth[target_id] = depth
                        next_frontier.append((target_id, next_path, next_edge_types))
            frontier = next_frontier[:frontier_limit]

        return results

    def find_config_propagation(self, limit: int = 50) -> list[dict[str, Any]]:
        """Find config keys read by multiple classes across services."""
        with self._store.pool.connection() as conn:
            rows = conn.execute("""
                SELECT n.name as config_key, n.project,
                       GROUP_CONCAT(DISTINCT ns.name) as reader_classes,
                       COUNT(DISTINCT ns.project) as service_count
                FROM nodes n
                JOIN edges e ON e.target_id = n.id AND e.type = 'READS_CONFIG'
                JOIN nodes ns ON ns.id = e.source_id
                WHERE n.type = 'ConfigKey'
                GROUP BY n.name
                HAVING service_count >= 2
                ORDER BY service_count DESC
                LIMIT ?
            """, (limit,)).fetchall()

        return [
            {
                "config_key": str(r["config_key"]),
                "readers": str(r["reader_classes"]).split(","),
                "service_count": int(r["service_count"]),
                "confidence": 0.7,
            }
            for r in rows
        ]
