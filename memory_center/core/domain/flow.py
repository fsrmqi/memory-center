"""Business flow — build, query, and extract structured business flows.

Combines BusinessFlowGraph (queryable flow graph with path analysis and
impact tracing) and BusinessFlowExtractor (BFS-based extraction from the
knowledge graph).  Implements UA-3 from NEXT_PHASE_MASTER_PLAN.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from ..graph import GraphStore
from ..storage.unified import UnifiedStore


@dataclass
class FlowNode:
    """A node in a business flow."""
    node_id: str
    name: str
    node_type: str
    step_order: int = 0
    service: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "name": self.name,
            "type": self.node_type,
            "step_order": self.step_order,
            "service": self.service,
        }


@dataclass
class FlowEdge:
    """An edge between flow nodes."""
    source_id: str
    target_id: str
    edge_type: str
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "type": self.edge_type,
            "confidence": self.confidence,
        }


@dataclass
class FlowPath:
    """A path through a business flow."""
    path_id: str
    nodes: List[str] = field(default_factory=list)
    edge_types: List[str] = field(default_factory=list)
    total_confidence: float = 0.0
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path_id": self.path_id,
            "nodes": self.nodes,
            "edge_types": self.edge_types,
            "total_confidence": round(self.total_confidence, 3),
            "description": self.description,
            "depth": len(self.nodes),
        }


@dataclass
class FlowStep:
    """A single step in a business flow."""
    node_id: str
    node_type: str
    name: str
    description: str = ""
    edge_type: str = ""
    confidence: float = 1.0


@dataclass
class BusinessFlow:
    """A business flow extracted from the knowledge graph."""
    flow_id: str
    name: str
    description: str = ""
    steps: List[FlowStep] = field(default_factory=list)
    entry_points: List[str] = field(default_factory=list)
    exit_points: List[str] = field(default_factory=list)
    entities_involved: List[str] = field(default_factory=list)
    risk_level: str = "low"


class BusinessFlowGraph:
    """Build and query a graph of business flows.

    Uses UnifiedStore for path queries, impact tracing, and flow graph building.
    """

    def __init__(self, store: UnifiedStore):
        self._store = store

    def build_flow_graph(self) -> Dict[str, Any]:
        """Build the complete business flow graph."""
        nodes: List[FlowNode] = []
        edges: List[FlowEdge] = []
        all_store_nodes = self._store.all_nodes()

        for node in all_store_nodes:
            ntype = node.get("type", "")
            nid = node.get("id", "")
            name = node.get("name", "")
            project = node.get("project", "")
            file_path = node.get("file_path", "")

            if ntype in ("Endpoint", "Class", "MQConsumer", "MQProducer", "FeignClient", "Service"):
                step = self._infer_step_order(ntype, file_path)
                nodes.append(FlowNode(
                    node_id=nid, name=name, node_type=ntype,
                    step_order=step, service=project,
                ))

        flow_node_ids = {n.node_id for n in nodes}
        for node in nodes:
            raw_edges = self._store.edges_for_node(node.node_id, direction="downstream", limit=50)
            for edge in raw_edges:
                src = edge.get("source_id", "")
                tgt = edge.get("target_id", "")
                if src in flow_node_ids and tgt in flow_node_ids:
                    edges.append(FlowEdge(
                        source_id=src, target_id=tgt,
                        edge_type=edge.get("type", ""),
                        confidence=float(edge.get("confidence", 1.0)),
                    ))

        return {
            "nodes": [n.to_dict() for n in nodes],
            "edges": [e.to_dict() for e in edges],
            "node_count": len(nodes),
            "edge_count": len(edges),
        }

    def trace_flow_from_endpoint(self, endpoint_id: str, max_depth: int = 5) -> FlowPath:
        """Trace the business flow starting from an endpoint."""
        path_nodes: List[str] = [endpoint_id]
        path_edges: List[str] = []
        visited: Set[str] = {endpoint_id}
        current = endpoint_id
        confidence = 1.0

        upstream = self._store.neighbors(current, direction="upstream", max_depth=1, limit=5)
        if upstream:
            parent = upstream[0]
            pid = parent.get("id", "")
            if pid and pid not in visited:
                visited.add(pid)
                path_nodes.append(pid)
                path_edges.append(self._get_edge_type(pid, current))
                current = pid
                confidence *= 0.95

        for _ in range(max_depth - 1):
            downstream = self._store.neighbors(current, direction="downstream", max_depth=1, limit=5)
            if not downstream:
                break

            best = None
            best_score = -1.0
            for neighbor in downstream:
                nid = neighbor.get("id", "")
                if nid in visited:
                    continue
                score = self._flow_relevance_score(neighbor.get("type", ""))
                if score > best_score:
                    best_score = score
                    best = neighbor

            if not best:
                break

            nid = best.get("id", "")
            visited.add(nid)
            path_nodes.append(nid)
            path_edges.append(self._get_edge_type(current, nid))
            confidence *= 0.9
            current = nid

        return FlowPath(
            path_id=f"flow_path:{endpoint_id}",
            nodes=path_nodes,
            edge_types=path_edges,
            total_confidence=confidence,
            description=f"从 {endpoint_id} 出发的业务流程路径",
        )

    def find_impact_along_flows(self, node_id: str, max_depth: int = 3) -> List[Dict[str, Any]]:
        """Find all nodes impacted by a change to node_id along business flows."""
        impacted: List[Dict[str, Any]] = []
        visited: Set[str] = set()
        queue = [(node_id, 0)]

        while queue:
            current, depth = queue.pop(0)
            if current in visited or depth > max_depth:
                continue
            visited.add(current)

            node = self._store.node_by_id(current)
            if node and current != node_id:
                impacted.append({
                    "node_id": current,
                    "name": node.get("name", ""),
                    "type": node.get("type", ""),
                    "depth": depth,
                })

            downstream = self._store.neighbors(current, direction="downstream", max_depth=1, limit=20)
            for neighbor in downstream:
                nid = neighbor.get("id", "")
                if nid not in visited:
                    queue.append((nid, depth + 1))

        return impacted

    def _infer_step_order(self, node_type: str, file_path: str) -> int:
        type_order = {"Endpoint": 1, "Class": 2, "FeignClient": 3, "MQProducer": 4, "MQConsumer": 5, "Service": 2}
        return type_order.get(node_type, 3)

    def _flow_relevance_score(self, node_type: str) -> float:
        scores = {
            "Class": 0.9, "Service": 0.85, "FeignClient": 0.8,
            "MQProducer": 0.75, "MQConsumer": 0.7, "Endpoint": 0.6,
            "Method": 0.5, "Field": 0.3,
        }
        return scores.get(node_type, 0.4)

    def _get_edge_type(self, source_id: str, target_id: str) -> str:
        with self._store.pool.connection() as conn:
            row = conn.execute(
                "SELECT type FROM edges WHERE source_id=? AND target_id=? LIMIT 1",
                (source_id, target_id),
            ).fetchone()
        if row:
            return row["type"] if isinstance(row, dict) else row[0]
        with self._store.pool.connection() as conn:
            row = conn.execute(
                "SELECT type FROM edges WHERE source_id=? AND target_id=? LIMIT 1",
                (target_id, source_id),
            ).fetchone()
        if row:
            return row["type"] if isinstance(row, dict) else row[0]
        return "UNKNOWN"


class BusinessFlowExtractor:
    """Extract business flows from the code knowledge graph."""

    def __init__(self, graph: GraphStore):
        self._graph = graph

    def extract_flows(self, seed_node_id: str, max_depth: int = 4, limit: int = 10) -> List[BusinessFlow]:
        """Extract business flows starting from a seed node."""
        flows: List[BusinessFlow] = []

        seed = self._graph.node_by_id(seed_node_id)
        if not seed:
            return flows

        steps: List[FlowStep] = []
        visited = {seed_node_id}
        frontier = [seed_node_id]

        for depth in range(max_depth):
            if not frontier:
                break
            next_frontier = []
            for nid in frontier:
                neighbors = self._graph.neighbors(nid, direction="downstream", max_depth=1, limit=20)
                for nb in neighbors:
                    target = nb.get("target", {})
                    tid = target.get("id", "")
                    if tid and tid not in visited:
                        visited.add(tid)
                        next_frontier.append(tid)
                        steps.append(FlowStep(
                            node_id=tid,
                            node_type=target.get("type", ""),
                            name=target.get("name", ""),
                            description=f"{seed.get('name', '')} -> {target.get('name', '')}",
                            edge_type=nb.get("type", ""),
                            confidence=float(nb.get("confidence", 0.5)),
                        ))
            frontier = next_frontier

        if steps:
            flow = BusinessFlow(
                flow_id=f"flow-{seed_node_id}",
                name=f"Flow from {seed.get('name', '')}",
                description=f"Business flow extracted from {seed.get('type', '')} {seed.get('name', '')}",
                steps=steps[:limit * 3],
                entry_points=[seed_node_id],
                exit_points=[s.node_id for s in steps[-3:]] if len(steps) >= 3 else [s.node_id for s in steps],
                entities_involved=list({s.name for s in steps}),
                risk_level="high" if len(steps) > 15 else "medium" if len(steps) > 8 else "low",
            )
            flows.append(flow)

        return flows
