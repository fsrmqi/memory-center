"""Graph pattern matching engine — find structural patterns in the code knowledge graph.

Supports declarative pattern queries like:
- "MQ consumers without idempotent protection"
- "Feign chains crossing 3+ services"
- "DTO modifications without downstream checks"
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..storage.runtime import RuntimeStore


@dataclass
class PatternMatch:
    """A single pattern match result."""
    pattern_name: str
    matched_nodes: list[dict[str, Any]]
    risk_level: str = "medium"
    description: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)


class GraphPatternEngine:
    """Declarative graph pattern matching using SQLite recursive CTEs."""

    def __init__(self, store: RuntimeStore):
        self._store = store

    # ── Built-in patterns ────────────────────────────────────────────────

    def find_unprotected_mq_consumers(self, limit: int = 50) -> list[PatternMatch]:
        """Find MQ consumers whose handler methods don't contain 'idempotent' or '幂等'."""
        with self._store.pool.connection() as conn:
            rows = conn.execute("""
                SELECT n.id, n.name, n.project, n.file_path, n.metadata_json
                FROM nodes n
                WHERE n.type = 'MQConsumer'
                LIMIT ?
            """, (limit,)).fetchall()

        matches = []
        for row in rows:
            meta = json.loads(row["metadata_json"] or "{}")
            method_name = meta.get("method_name", "")
            class_name = meta.get("class_name", "")
            # Heuristic: if method/class name doesn't suggest idempotent handling
            name_lower = (method_name + " " + class_name).lower()
            if "idempotent" not in name_lower and "幂等" not in name_lower:
                matches.append(PatternMatch(
                    pattern_name="unprotected_mq_consumer",
                    matched_nodes=[dict(row)],
                    risk_level="high",
                    description=f"MQ 消费者 {class_name}.{method_name} 可能缺少幂等保护",
                    evidence={"topic": meta.get("topic", ""), "class": class_name, "method": method_name},
                ))
        return matches

    def find_long_feign_chains(self, min_depth: int = 3, limit: int = 50) -> list[PatternMatch]:
        """Find Feign call chains crossing multiple services."""
        with self._store.pool.connection() as conn:
            # Find FeignClient nodes that call services, which in turn have FeignClients
            rows = conn.execute("""
                WITH RECURSIVE feign_chain(fc_id, service_id, depth) AS (
                    SELECT n.id, e.target_id, 1
                    FROM nodes n
                    JOIN edges e ON e.source_id = n.id AND e.type = 'CALLS_SERVICE'
                    WHERE n.type = 'FeignClient'
                    UNION
                    SELECT fc.fc_id, e2.target_id, fc.depth + 1
                    FROM feign_chain fc
                    JOIN edges e1 ON e1.source_id = fc.service_id AND e1.type = 'CONTAINS'
                    JOIN nodes n2 ON n2.id = e1.target_id AND n2.type = 'FeignClient'
                    JOIN edges e2 ON e2.source_id = n2.id AND e2.type = 'CALLS_SERVICE'
                    WHERE fc.depth < ?
                )
                SELECT fc_id, MAX(depth) as max_depth
                FROM feign_chain
                GROUP BY fc_id
                HAVING max_depth >= ?
                LIMIT ?
            """, (min_depth, min_depth, limit)).fetchall()

        matches = []
        for row in rows:
            fc_id = row["fc_id"]
            node = self._store.node_by_id(fc_id)
            if node:
                matches.append(PatternMatch(
                    pattern_name="long_feign_chain",
                    matched_nodes=[node],
                    risk_level="medium",
                    description=f"Feign 客户端 {node.get('name', '')} 存在 {row['max_depth']} 层跨服务调用链",
                    evidence={"depth": row["max_depth"]},
                ))
        return matches

    def find_shared_configs(self, limit: int = 50) -> list[PatternMatch]:
        """Find config keys read by multiple services."""
        with self._store.pool.connection() as conn:
            rows = conn.execute("""
                SELECT n.name, n.project, COUNT(DISTINCT e.source_id) as reader_count
                FROM nodes n
                JOIN edges e ON e.target_id = n.id AND e.type = 'READS_CONFIG'
                WHERE n.type = 'ConfigKey'
                GROUP BY n.name
                HAVING reader_count >= 2
                ORDER BY reader_count DESC
                LIMIT ?
            """, (limit,)).fetchall()

        matches = []
        for row in rows:
            matches.append(PatternMatch(
                pattern_name="shared_config",
                matched_nodes=[{"name": row["name"], "project": row["project"]}],
                risk_level="medium",
                description=f"配置项 {row['name']} 被 {row['reader_count']} 个服务读取",
                evidence={"reader_count": row["reader_count"]},
            ))
        return matches

    def run_all_patterns(self) -> dict[str, list[PatternMatch]]:
        """Run all built-in patterns and return results grouped by pattern name."""
        return {
            "unprotected_mq_consumers": self.find_unprotected_mq_consumers(),
            "long_feign_chains": self.find_long_feign_chains(),
            "shared_configs": self.find_shared_configs(),
        }
