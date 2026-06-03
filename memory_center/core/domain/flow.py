"""Business flow graph — build and query structured business flows.

Provides a higher-level abstraction over BusinessDomainExtractor's flow
extraction, supporting flow querying, path analysis, and impact tracing
along business flows.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

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


class BusinessFlowGraph:
    """Build and query a graph of business flows.

    Unlike BusinessDomainExtractor which extracts flat domain+flow lists,
    this class builds a queryable flow graph supporting path queries and
    impact analysis along business flows.
    """

    def __init__(self, store: UnifiedStore):
        self._store = store

    def build_flow_graph(self) -> Dict[str, Any]:
        """Build the complete business flow graph."""
        nodes: List[FlowNode] = []
        edges: List[FlowEdge] = []
        all_store_nodes = self._store.all_nodes()

        # Collect endpoints, controllers, services, MQ
        for node in all_store_nodes:
            ntype = node.get("type", "")
            nid = node.get("id", "")
            name = node.get("name", "")
            project = node.get("project", "")
            file_path = node.get("file_path", "")

            if ntype in ("Endpoint", "Class", "MQConsumer", "MQProducer", "FeignClient", "Service"):
                step = self._infer_step_order(ntype, file_path)
                nodes.append(FlowNode(
                    node_id=nid,
                    name=name,
                    node_type=ntype,
                    step_order=step,
                    service=project,
                ))

        # Collect edges between flow-relevant nodes
        flow_node_ids = {n.node_id for n in nodes}
        for node in nodes:
            raw_edges = self._store.edges_for_node(node.node_id, direction="downstream", limit=50)
            for edge in raw_edges:
                src = edge.get("source_id", "")
                tgt = edge.get("target_id", "")
                if src in flow_node_ids and tgt in flow_node_ids:
                    edges.append(FlowEdge(
                        source_id=src,
                        target_id=tgt,
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

        # First go upstream from the endpoint to find the controller that
        # exposes it (EXPOSES_ENDPOINT edges go Controller→Endpoint).
        upstream = self._store.neighbors(current, direction="upstream", max_depth=1, limit=5)
        if upstream:
            parent = upstream[0]
            pid = parent.get("id", "")
            if pid and pid not in visited:
                visited.add(pid)
                path_nodes.append(pid)
                edge_type = self._get_edge_type(pid, current)
                path_edges.append(edge_type)
                current = pid
                confidence *= 0.95

        # Then trace downstream from the controller through the service layer.
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
                ntype = neighbor.get("type", "")
                score = self._flow_relevance_score(ntype)
                if score > best_score:
                    best_score = score
                    best = neighbor

            if not best:
                break

            nid = best.get("id", "")
            visited.add(nid)
            path_nodes.append(nid)
            # Look up the actual edge type between current and best
            edge_type = self._get_edge_type(current, nid)
            path_edges.append(edge_type)
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
        """Infer the order of a node in a business flow based on its type and path."""
        type_order = {
            "Endpoint": 1,
            "Class": 2,
            "FeignClient": 3,
            "MQProducer": 4,
            "MQConsumer": 5,
            "Service": 2,
        }
        return type_order.get(node_type, 3)

    def _flow_relevance_score(self, node_type: str) -> float:
        """Score how relevant a node type is for business flow tracing."""
        scores = {
            "Class": 0.9,
            "Service": 0.85,
            "FeignClient": 0.8,
            "MQProducer": 0.75,
            "MQConsumer": 0.7,
            "Endpoint": 0.6,
            "Method": 0.5,
            "Field": 0.3,
        }
        return scores.get(node_type, 0.4)

    def _get_edge_type(self, source_id: str, target_id: str) -> str:
        """Look up the edge type between two nodes."""
        with self._store.pool.connection() as conn:
            row = conn.execute(
                "SELECT type FROM edges WHERE source_id=? AND target_id=? LIMIT 1",
                (source_id, target_id),
            ).fetchone()
        if row:
            return row["type"] if isinstance(row, dict) else row[0]
        # Also check reverse direction
        with self._store.pool.connection() as conn:
            row = conn.execute(
                "SELECT type FROM edges WHERE source_id=? AND target_id=? LIMIT 1",
                (target_id, source_id),
            ).fetchone()
        if row:
            return row["type"] if isinstance(row, dict) else row[0]
        return "UNKNOWN"
