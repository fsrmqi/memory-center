"""Risk pattern engine — detect risk patterns in the code knowledge graph.

Combines graph structure analysis with rule matching to identify
potential risks before code changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from memory_center.core.governance.rules import match_rules

from ..storage.unified import UnifiedStore


@dataclass
class RiskFinding:
    pattern: str
    severity: str  # high | medium | low
    description: str
    affected_nodes: list[dict[str, Any]] = field(default_factory=list)
    checklist: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)


class RiskPatternEngine:
    """Detect risk patterns combining graph analysis + rules."""

    def __init__(self, store: UnifiedStore, workspace_store: Any = None):
        self._store = store
        self._ws_store = workspace_store

    def analyze_change_risk(
        self,
        target_id: str,
        change_type: str = "modify",
    ) -> list[RiskFinding]:
        """Analyze risks for changing a specific node."""
        findings = []
        node = self._store.node_by_id(target_id)
        if not node:
            return findings

        node_type = node.get("type", "")
        node_name = node.get("name", "")
        file_path = node.get("file_path", "")

        # 1. Check if it's a public contract (high risk)
        if node_type in ("FeignClient", "FeignMethod", "Endpoint"):
            downstream = self._store.neighbors(target_id, direction="upstream", max_depth=2, limit=50)
            findings.append(RiskFinding(
                pattern="public_contract_change",
                severity="high",
                description=f"修改公共契约 {node_name} 可能影响 {len(downstream)} 个上游调用方",
                affected_nodes=downstream[:10],
                checklist=[
                    "搜索所有使用该契约的服务",
                    "检查字段兼容性",
                    "通知下游团队",
                ],
                evidence={"node_type": node_type, "upstream_count": len(downstream)},
            ))

        # 2. Check if it's a DTO with many usages
        if node_type == "Field" or (node_type == "Class" and "DTO" in node_name.upper()):
            usages = self._store.neighbors(target_id, direction="both", max_depth=2, limit=100)
            if len(usages) > 5:
                findings.append(RiskFinding(
                    pattern="widely_used_dto",
                    severity="high",
                    description=f"DTO {node_name} 被 {len(usages)} 处引用，修改需谨慎",
                    affected_nodes=usages[:10],
                    checklist=[
                        "检查所有 getter/setter 使用点",
                        "验证序列化兼容性",
                        "检查 MQ 消息体是否包含该字段",
                    ],
                ))

        # 3. Check if MQ consumer lacks idempotent handling
        if node_type in ("MQConsumer", "MQTopic"):
            findings.append(RiskFinding(
                pattern="mq_change_risk",
                severity="medium",
                description=f"MQ 相关节点 {node_name} 变更，需确认消费幂等性",
                checklist=[
                    "确认消费者有幂等保护",
                    "检查消息格式兼容性",
                    "验证 topic/group 配置",
                ],
            ))

        # 4. Match rules from the workspace
        if self._ws_store:
            rules = match_rules(self._ws_store, intent=node_name, files=[file_path] if file_path else [])
            for rule in rules[:3]:
                findings.append(RiskFinding(
                    pattern=f"rule_{rule.get('id', 'unknown')}",
                    severity=rule.get("severity", "medium"),
                    description=rule.get("rule", ""),
                    checklist=rule.get("checklist", []),
                    evidence={"rule_id": rule.get("id", ""), "score": rule.get("score", 0)},
                ))

        return findings

    def scan_workspace_risks(self, limit: int = 20) -> list[RiskFinding]:
        """Scan the entire workspace for risk patterns."""
        findings = []

        # 1. Unprotected MQ consumers
        with self._store.pool.connection() as conn:
            mq_consumers = conn.execute(
                "SELECT * FROM nodes WHERE type='MQConsumer' LIMIT ?", (limit,)
            ).fetchall()

        for row in mq_consumers:
            node = dict(row)
            findings.append(RiskFinding(
                pattern="unprotected_mq_consumer",
                severity="high",
                description=f"MQ 消费者 {node.get('name', '')} 可能缺少幂等保护",
                affected_nodes=[node],
                checklist=["检查是否有业务唯一键去重", "验证重复消费处理逻辑"],
            ))

        # 2. Long dependency chains
        with self._store.pool.connection() as conn:
            long_chains = conn.execute("""
                SELECT source_id, COUNT(*) as depth
                FROM edges
                WHERE type IN ('CALLS_METHOD', 'CALLS_SERVICE')
                GROUP BY source_id
                HAVING depth > 5
                LIMIT ?
            """, (limit,)).fetchall()

        for row in long_chains:
            node = self._store.node_by_id(row["source_id"])
            if node:
                findings.append(RiskFinding(
                    pattern="deep_dependency",
                    severity="medium",
                    description=f"节点 {node.get('name', '')} 有 {row['depth']} 条出边，依赖过深",
                    affected_nodes=[node],
                    evidence={"out_degree": row["depth"]},
                ))

        return findings
