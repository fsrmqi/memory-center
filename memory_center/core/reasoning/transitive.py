"""Transitive inference engine — derive implicit relationships from the graph.

E.g., if A calls B and B calls C, infer A transitively calls C.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from ..storage.unified import UnifiedStore


@dataclass
class TransitiveRelation:
    source_id: str
    target_id: str
    path: List[str]  # intermediate node IDs
    edge_types: List[str]
    confidence: float


class TransitiveInferenceEngine:
    """Derive transitive relationships using recursive CTEs."""

    def __init__(self, store: UnifiedStore):
        self._store = store

    def find_transitive_calls(
        self,
        source_id: str,
        max_depth: int = 3,
        limit: int = 50,
    ) -> List[TransitiveRelation]:
        """Find all nodes transitively reachable from source via CALLS_METHOD / CALLS_SERVICE edges."""
        with self._store.pool.connection() as conn:
            rows = conn.execute("""
                WITH RECURSIVE chain(src, tgt, path, edge_types, depth) AS (
                    SELECT e.source_id, e.target_id,
                           e.source_id || ',' || e.target_id,
                           e.type, 1
                    FROM edges e
                    WHERE e.source_id = ?
                      AND e.type IN ('CALLS_METHOD', 'CALLS_SERVICE')
                    UNION ALL
                    SELECT c.src, e.target_id,
                           c.path || ',' || e.target_id,
                           c.edge_types || ',' || e.type,
                           c.depth + 1
                    FROM chain c
                    JOIN edges e ON e.source_id = c.tgt
                    WHERE e.type IN ('CALLS_METHOD', 'CALLS_SERVICE')
                      AND c.depth < ?
                      AND c.path NOT LIKE '%' || e.target_id || '%'
                )
                SELECT src, tgt, path, edge_types, depth
                FROM chain
                WHERE depth >= 2
                ORDER BY depth
                LIMIT ?
            """, (source_id, max_depth, limit)).fetchall()

        results = []
        for row in rows:
            path = str(row["path"]).split(",")
            confidence = max(0.3, 1.0 - 0.2 * int(row["depth"]))
            results.append(TransitiveRelation(
                source_id=str(row["src"]),
                target_id=str(row["tgt"]),
                path=path,
                edge_types=str(row["edge_types"]).split(","),
                confidence=round(confidence, 2),
            ))
        return results

    def find_config_propagation(self, limit: int = 50) -> List[Dict[str, Any]]:
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
