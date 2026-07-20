"""Graph view builders — produce structured views for different personas.

Supports three modes:
- Architecture Mode: services, modules, interfaces, MQ, config, dependency chains
- Business Mode: business domains, flows, entry points, state transitions
- Change Mode: current diff, impact radius, risk rules, verification checklist
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..domain.extractor import BusinessDomainExtractor
from ..reasoning.risk import RiskFinding, RiskPatternEngine
from ..storage.runtime import RuntimeStore


@dataclass
class GraphView:
    """A structured graph view for a specific mode."""
    mode: str  # architecture | business | change
    title: str
    description: str = ""
    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    groups: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    persona: str = "developer"

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "title": self.title,
            "description": self.description,
            "nodes": self.nodes,
            "edges": self.edges,
            "groups": self.groups,
            "metadata": self.metadata,
            "persona": self.persona,
        }


class GraphViewBuilder:
    """Build structured graph views for different use cases."""

    def __init__(self, store: RuntimeStore):
        self._store = store

    def build(
        self,
        mode: str,
        target: str | None = None,
        persona: str = "developer",
    ) -> GraphView:
        """Build a graph view for the specified mode."""
        if mode == "architecture":
            return self._build_architecture_view(target, persona)
        elif mode == "business":
            return self._build_business_view(target, persona)
        elif mode == "change":
            return self._build_change_view(target, persona)
        else:
            raise ValueError(f"Unknown graph view mode: {mode}")

    def _build_architecture_view(self, target: str | None, persona: str) -> GraphView:
        """Build architecture-focused view."""
        nodes = self._store.all_nodes()
        all_edges = []

        # Collect edges
        for node in nodes:
            node_id = node.get("id", "")
            edges = self._store.edges_for_node(node_id, direction="downstream", limit=50)
            all_edges.extend(edges)

        # Group by type
        groups = []
        type_nodes: dict[str, list[dict[str, Any]]] = {}
        for node in nodes:
            node_type = node.get("type", "unknown")
            type_nodes.setdefault(node_type, []).append(node)

        for node_type, group_nodes in type_nodes.items():
            groups.append({
                "id": f"group:{node_type}",
                "label": node_type,
                "count": len(group_nodes),
                "node_ids": [n.get("id", "") for n in group_nodes[:20]],
            })

        # Deduplicate edges
        seen_edge_ids = set()
        unique_edges = []
        for edge in all_edges:
            edge_id = edge.get("id", "")
            if edge_id not in seen_edge_ids:
                seen_edge_ids.add(edge_id)
                unique_edges.append(edge)

        return GraphView(
            mode="architecture",
            title="架构视图",
            description=f"共 {len(nodes)} 个节点, {len(unique_edges)} 条边",
            nodes=nodes,
            edges=unique_edges[:200],
            groups=groups,
            metadata={"total_nodes": len(nodes), "total_edges": len(unique_edges)},
            persona=persona,
        )

    def _build_business_view(self, target: str | None, persona: str) -> GraphView:
        """Build business-domain-focused view."""
        extractor = BusinessDomainExtractor(self._store)
        domains = extractor.extract_domains()
        flows = extractor.extract_flows()

        # Build domain groups
        groups = []
        for domain in domains:
            groups.append({
                "id": domain.domain_id,
                "label": domain.name,
                "description": domain.description,
                "services": domain.services,
                "entity_count": len(domain.entities),
                "confidence": domain.confidence,
            })

        # Build flow edges
        flow_edges = []
        for flow in flows:
            for i in range(len(flow.steps) - 1):
                flow_edges.append({
                    "id": f"flow_edge:{flow.flow_id}:{i}",
                    "source_id": flow.steps[i].get("node_id", ""),
                    "target_id": flow.steps[i + 1].get("node_id", ""),
                    "type": "NEXT_STEP",
                    "flow_name": flow.name,
                })

        return GraphView(
            mode="business",
            title="业务视图",
            description=f"发现 {len(domains)} 个业务域, {len(flows)} 条业务流程",
            nodes=[d.to_dict() for d in domains],
            edges=flow_edges[:100],
            groups=groups,
            metadata={"domain_count": len(domains), "flow_count": len(flows)},
            persona=persona,
        )

    def _build_change_view(self, target: str | None, persona: str) -> GraphView:
        """Build change-impact-focused view."""
        risk_engine = RiskPatternEngine(self._store)

        if target:
            # Analyze specific target
            findings = risk_engine.analyze_change_risk(target)
            node = self._store.node_by_id(target)
            neighbors = self._store.neighbors(target, direction="both", max_depth=2, limit=50)
        else:
            # Scan entire workspace
            findings = risk_engine.scan_workspace_risks()
            node = None
            neighbors = []

        # Build risk groups
        groups = []
        severity_groups: dict[str, list[RiskFinding]] = {}
        for finding in findings:
            severity_groups.setdefault(finding.severity, []).append(finding)

        for severity, severity_findings in severity_groups.items():
            groups.append({
                "id": f"risk_group:{severity}",
                "label": f"{severity} risk",
                "count": len(severity_findings),
                "patterns": [f.pattern for f in severity_findings],
            })

        # Build checklist from findings
        checklist = []
        for finding in findings:
            checklist.extend(finding.checklist)
        checklist = list(dict.fromkeys(checklist))  # deduplicate preserving order

        metadata = {
            "target": target,
            "finding_count": len(findings),
            "checklist_count": len(checklist),
        }
        if node:
            metadata["target_node"] = node

        return GraphView(
            mode="change",
            title="变更影响视图",
            description=f"发现 {len(findings)} 个风险点, {len(checklist)} 项检查清单",
            nodes=neighbors,
            edges=[],
            groups=groups,
            metadata=metadata,
            persona=persona,
        )
