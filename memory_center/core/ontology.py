"""Code Knowledge Graph Ontology — typed models for V3 node and edge types.

Defines the core node types and edge types used by the ontology and graph layers.
These are dataclass models used for type-safe construction and validation
of code knowledge graph entities.
"""
from __future__ import annotations

import json
import re as _re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ═══════════════════════════════════════════════════════════════════════════════
# Node Types — §3.3 + §20.5.1
# ═══════════════════════════════════════════════════════════════════════════════

# Standard node types (already in 2.x)
NODE_TYPE_SERVICE = "Service"
NODE_TYPE_CLASS = "Class"
NODE_TYPE_METHOD = "Method"
NODE_TYPE_FIELD = "Field"
NODE_TYPE_INTERFACE = "Interface"
NODE_TYPE_FEIGN_CLIENT = "FeignClient"
NODE_TYPE_FEIGN_METHOD = "FeignMethod"
NODE_TYPE_ENDPOINT = "Endpoint"
NODE_TYPE_MQ_TOPIC = "MQTopic"
NODE_TYPE_MQ_CONSUMER = "MQConsumer"
NODE_TYPE_MQ_PRODUCER = "MQProducer"
NODE_TYPE_CONFIG_KEY = "ConfigKey"

# New V3 node types — §3.3
NODE_TYPE_CODE_SUMMARY = "CodeSummary"
NODE_TYPE_BUSINESS_INTENT = "BusinessIntent"
NODE_TYPE_RISK_PATTERN = "RiskPattern"
NODE_TYPE_ARCHITECTURAL_LAYER = "ArchitecturalLayer"
NODE_TYPE_DATA_FLOW_NODE = "DataFlowNode"

# New V3 node types — §20.5.1
NODE_TYPE_ROUTE = "RouteNode"
NODE_TYPE_BUSINESS_FLOW = "BusinessFlow"
NODE_TYPE_FLOW_STEP = "FlowStep"
NODE_TYPE_ARCHITECTURE_TOUR = "ArchitectureTour"
NODE_TYPE_INDEX_FRESHNESS = "IndexFreshness"

ALL_NODE_TYPES = frozenset({
    NODE_TYPE_SERVICE, NODE_TYPE_CLASS, NODE_TYPE_METHOD, NODE_TYPE_FIELD,
    NODE_TYPE_INTERFACE, NODE_TYPE_FEIGN_CLIENT, NODE_TYPE_FEIGN_METHOD,
    NODE_TYPE_ENDPOINT, NODE_TYPE_MQ_TOPIC, NODE_TYPE_MQ_CONSUMER,
    NODE_TYPE_MQ_PRODUCER, NODE_TYPE_CONFIG_KEY,
    NODE_TYPE_CODE_SUMMARY, NODE_TYPE_BUSINESS_INTENT, NODE_TYPE_RISK_PATTERN,
    NODE_TYPE_ARCHITECTURAL_LAYER, NODE_TYPE_DATA_FLOW_NODE,
    NODE_TYPE_ROUTE, NODE_TYPE_BUSINESS_FLOW, NODE_TYPE_FLOW_STEP,
    NODE_TYPE_ARCHITECTURE_TOUR, NODE_TYPE_INDEX_FRESHNESS,
})


# ═══════════════════════════════════════════════════════════════════════════════
# Edge Types — §3.4 + §20.5.2
# ═══════════════════════════════════════════════════════════════════════════════

# Standard edge types (already in 2.x)
EDGE_TYPE_CALLS_METHOD = "CALLS_METHOD"
EDGE_TYPE_CALLS_SERVICE = "CALLS_SERVICE"
EDGE_TYPE_INJECTS = "INJECTS"
EDGE_TYPE_IMPORTS = "IMPORTS"
EDGE_TYPE_CONTAINS = "CONTAINS"
EDGE_TYPE_CONSUMES_TOPIC = "CONSUMES_TOPIC"
EDGE_TYPE_PRODUCES_TOPIC = "PRODUCES_TOPIC"
EDGE_TYPE_READS_CONFIG = "READS_CONFIG"
EDGE_TYPE_EXPOSES_ENDPOINT = "EXPOSES_ENDPOINT"
EDGE_TYPE_DECLARES = "DECLARES"

# New V3 edge types — §3.4
EDGE_TYPE_TRANSITIVELY_CALLS = "TRANSITIVELY_CALLS"
EDGE_TYPE_DATA_FLOWS_TO = "DATA_FLOWS_TO"
EDGE_TYPE_CONFIG_PROPAGATES = "CONFIG_PROPAGATES"
EDGE_TYPE_HISTORICALLY_RELATED = "HISTORICALLY_RELATED"
EDGE_TYPE_SEMANTIC_SIMILAR = "SEMANTIC_SIMILAR"
EDGE_TYPE_RISK_CORRELATED = "RISK_CORRELATED"

# New V3 edge types — §20.5.2
EDGE_TYPE_ROUTES_TO = "ROUTES_TO"
EDGE_TYPE_IMPLEMENTS_FLOW_STEP = "IMPLEMENTS_FLOW_STEP"
EDGE_TYPE_NEXT_STEP = "NEXT_STEP"
EDGE_TYPE_EXPLAINS = "EXPLAINS"
EDGE_TYPE_STALE_FOR = "STALE_FOR"

ALL_EDGE_TYPES = frozenset({
    EDGE_TYPE_CALLS_METHOD, EDGE_TYPE_CALLS_SERVICE, EDGE_TYPE_INJECTS,
    EDGE_TYPE_IMPORTS, EDGE_TYPE_CONTAINS, EDGE_TYPE_CONSUMES_TOPIC,
    EDGE_TYPE_PRODUCES_TOPIC, EDGE_TYPE_READS_CONFIG, EDGE_TYPE_EXPOSES_ENDPOINT,
    EDGE_TYPE_DECLARES,
    EDGE_TYPE_TRANSITIVELY_CALLS, EDGE_TYPE_DATA_FLOWS_TO,
    EDGE_TYPE_CONFIG_PROPAGATES, EDGE_TYPE_HISTORICALLY_RELATED,
    EDGE_TYPE_SEMANTIC_SIMILAR, EDGE_TYPE_RISK_CORRELATED,
    EDGE_TYPE_ROUTES_TO, EDGE_TYPE_IMPLEMENTS_FLOW_STEP,
    EDGE_TYPE_NEXT_STEP, EDGE_TYPE_EXPLAINS, EDGE_TYPE_STALE_FOR,
})

# Semantic strength classification per §3.4
EDGE_SEMANTIC_STRENGTH: Dict[str, str] = {
    EDGE_TYPE_CALLS_METHOD: "confirmed",
    EDGE_TYPE_CALLS_SERVICE: "confirmed",
    EDGE_TYPE_INJECTS: "confirmed",
    EDGE_TYPE_IMPORTS: "confirmed",
    EDGE_TYPE_CONTAINS: "confirmed",
    EDGE_TYPE_CONSUMES_TOPIC: "confirmed",
    EDGE_TYPE_PRODUCES_TOPIC: "confirmed",
    EDGE_TYPE_READS_CONFIG: "confirmed",
    EDGE_TYPE_EXPOSES_ENDPOINT: "confirmed",
    EDGE_TYPE_DECLARES: "confirmed",
    EDGE_TYPE_TRANSITIVELY_CALLS: "derived",
    EDGE_TYPE_DATA_FLOWS_TO: "inferred",
    EDGE_TYPE_CONFIG_PROPAGATES: "inferred",
    EDGE_TYPE_HISTORICALLY_RELATED: "derived",
    EDGE_TYPE_SEMANTIC_SIMILAR: "derived",
    EDGE_TYPE_RISK_CORRELATED: "derived",
    EDGE_TYPE_ROUTES_TO: "confirmed",
    EDGE_TYPE_IMPLEMENTS_FLOW_STEP: "inferred",
    EDGE_TYPE_NEXT_STEP: "inferred",
    EDGE_TYPE_EXPLAINS: "derived",
    EDGE_TYPE_STALE_FOR: "runtime",
}

# Default confidence ranges per §3.4
EDGE_CONFIDENCE_RANGES: Dict[str, tuple[float, float]] = {
    EDGE_TYPE_TRANSITIVELY_CALLS: (0.4, 0.6),
    EDGE_TYPE_DATA_FLOWS_TO: (0.5, 0.7),
    EDGE_TYPE_CONFIG_PROPAGATES: (0.7, 0.7),
    EDGE_TYPE_HISTORICALLY_RELATED: (0.3, 0.5),
    EDGE_TYPE_SEMANTIC_SIMILAR: (0.3, 0.8),
    EDGE_TYPE_RISK_CORRELATED: (0.4, 0.7),
    EDGE_TYPE_ROUTES_TO: (0.7, 0.95),
    EDGE_TYPE_IMPLEMENTS_FLOW_STEP: (0.4, 0.8),
    EDGE_TYPE_NEXT_STEP: (0.4, 0.8),
    EDGE_TYPE_EXPLAINS: (0.6, 0.9),
    EDGE_TYPE_STALE_FOR: (1.0, 1.0),
}


@dataclass(frozen=True)
class RouteNode:
    """HTTP/RPC/MQ entry route — §20.5.1."""
    route_id: str
    route_type: str  # http | rpc | mq
    method: str = ""
    path: str = ""
    topic: str = ""
    handler_entity: str = ""
    service: str = ""

    def to_node_tuple(self) -> tuple[str, str, str, str, str, int, str]:
        """Convert to UnifiedStore.upsert_nodes compatible tuple."""
        meta = {
            "route_type": self.route_type,
            "method": self.method,
            "path": self.path,
            "topic": self.topic,
            "handler_entity": self.handler_entity,
        }
        return (self.route_id, NODE_TYPE_ROUTE, self.path or self.topic or self.route_id,
                self.service, "", 0, json.dumps(meta, ensure_ascii=False))


@dataclass(frozen=True)
class ArchLayer:
    """Architectural layer classification — §3.3."""
    layer_id: str
    name: str  # controller | service | dao | infra | config | mq
    service: str = ""
    description: str = ""

    def to_node_tuple(self) -> tuple[str, str, str, str, str, int, str]:
        meta = {"description": self.description}
        return (self.layer_id, NODE_TYPE_ARCHITECTURAL_LAYER, self.name,
                self.service, "", 0, json.dumps(meta, ensure_ascii=False))


@dataclass(frozen=True)
class CodeSummaryNode:
    """Semantic summary for a code entity — §3.3."""
    summary_id: str
    target_entity: str  # node ID of the summarized entity
    summary: str = ""
    source: str = "rule"  # rule | llm

    def to_node_tuple(self) -> tuple[str, str, str, str, str, int, str]:
        meta = {"target_entity": self.target_entity, "source": self.source}
        return (self.summary_id, NODE_TYPE_CODE_SUMMARY, self.summary[:80],
                "", "", 0, json.dumps(meta, ensure_ascii=False))


@dataclass(frozen=True)
class DataFlowNode:
    """Data flow node — §3.3."""
    flow_id: str
    field_name: str
    entity_type: str = ""  # DTO | config | MQ body
    service: str = ""

    def to_node_tuple(self) -> tuple[str, str, str, str, str, int, str]:
        meta = {"entity_type": self.entity_type}
        return (self.flow_id, NODE_TYPE_DATA_FLOW_NODE, self.field_name,
                self.service, "", 0, json.dumps(meta, ensure_ascii=False))


def validate_node_type(node_type: str) -> bool:
    """Check if a node type is in the known ontology."""
    return node_type in ALL_NODE_TYPES


def validate_edge_type(edge_type: str) -> bool:
    """Check if an edge type is in the known ontology."""
    return edge_type in ALL_EDGE_TYPES


def edge_strength(edge_type: str) -> str:
    """Return semantic strength for an edge type."""
    return EDGE_SEMANTIC_STRENGTH.get(edge_type, "unknown")


def edge_confidence_range(edge_type: str) -> tuple[float, float]:
    """Return (min, max) confidence range for an edge type."""
    return EDGE_CONFIDENCE_RANGES.get(edge_type, (0.0, 1.0))


# ═══════════════════════════════════════════════════════════════════════════════
# Entity Validator — enforce ontology constraints from ONTOLOGY.md §5
# ═══════════════════════════════════════════════════════════════════════════════

# Java naming patterns that indicate Feign clients (§5.1)
_FEIGN_NAME_PATTERNS = (
    "feignclient", "feign_client",  # *FeignClient naming
    "fegin",  # common typo in Chinese projects
)

# Regex patterns per ONTOLOGY.md §5.1: Feign*Service or *FeignClient
_FEIGN_NAME_REGEXES = (
    _re.compile(r"^feign", _re.IGNORECASE),       # Feign*Service
    _re.compile(r"feign(client|service)", _re.IGNORECASE),  # *FeignClient, *FeignService
    _re.compile(r"fegin", _re.IGNORECASE),         # typo variant
)

# Structural classification of node types
_STRUCTURAL_TYPES = frozenset({"Service", "File"})
_DECLARATIVE_TYPES = frozenset({"Class", "Method", "Field", "Interface"})
_CONTRACT_TYPES = frozenset({"Endpoint", "FeignClient", "FeignMethod", "MQTopic", "MQConsumer", "MQProducer"})
_INFERRED_TYPES = frozenset({"Bean", "DataResource"})
_MEMORY_TYPES = frozenset({"SessionEvent", "WriteReceipt", "Ref", "Task", "Handoff", "ResumePacket"})
_V3_TYPES = frozenset({
    "CodeSummary", "BusinessIntent", "RiskPattern", "ArchitecturalLayer",
    "DataFlowNode", "RouteNode", "BusinessFlow", "FlowStep",
    "ArchitectureTour", "IndexFreshness",
})


class EntityValidator:
    """Validate entity classification against ontology constraints.

    Enforces the rules from ONTOLOGY.md §5:
    - Service ≠ FeignClient (§5.1)
    - Endpoint ≠ Controller (§5.2)
    - Ref ≠ raw data (§5.3)
    - Task / Session / Receipt are different layers (§5.4)
    - Endpoint paths must be specific enough (§5.5)
    """

    @staticmethod
    def is_feign_entity(name: str, node_type: str = "", metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Check if an entity should be classified as a Feign client.

        Per §5.1: only classify as Feign if:
        - Name matches Feign*Service or *FeignClient patterns
        - Has @FeignClient annotation (in metadata)
        - Registered in feign-index
        """
        name_lower = name.lower()
        # Check naming patterns
        if any(pat in name_lower for pat in _FEIGN_NAME_PATTERNS):
            return True
        # Check regex patterns per §5.1: Feign*Service or *FeignClient
        if any(rx.search(name) for rx in _FEIGN_NAME_REGEXES):
            return True
        # Check metadata for annotation
        meta = metadata or {}
        if meta.get("has_feign_annotation") or meta.get("feign_client"):
            return True
        # Check node type
        if node_type in ("FeignClient", "FeignMethod"):
            return True
        return False

    @staticmethod
    def is_local_service(name: str, node_type: str = "", metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Check if an entity is a local service (not a Feign client).

        Per §5.1: *ServiceImpl, *Service (without Feign prefix) are local.
        """
        if EntityValidator.is_feign_entity(name, node_type, metadata):
            return False
        name_lower = name.lower()
        return (
            node_type == "Class" and
            ("service" in name_lower or "impl" in name_lower or "dao" in name_lower)
        )

    @staticmethod
    def validate_endpoint_path(path: str) -> Dict[str, Any]:
        """Validate endpoint path specificity per §5.5.

        Only paths with ≥2 segments (e.g. /api/users) should participate
        in Feign→API auto-association.
        """
        segments = [s for s in path.split("/") if s]
        is_specific = len(segments) >= 2
        return {
            "path": path,
            "segments": len(segments),
            "is_specific": is_specific,
            "confidence": 0.9 if is_specific else 0.1,
        }

    @staticmethod
    def classify_entity_category(node_type: str) -> str:
        """Classify an entity into its ontology category."""
        if node_type in _STRUCTURAL_TYPES:
            return "structural"
        if node_type in _DECLARATIVE_TYPES:
            return "declarative"
        if node_type in _CONTRACT_TYPES:
            return "contractual"
        if node_type in _INFERRED_TYPES:
            return "inferential"
        if node_type in _MEMORY_TYPES:
            return "memory"
        if node_type in _V3_TYPES:
            return "v3_extended"
        return "unknown"

    @staticmethod
    def validate_memory_layer(node_type: str) -> Dict[str, Any]:
        """Validate memory entity layer assignment per §5.4."""
        layer_map = {
            "SessionEvent": "L0",
            "WriteReceipt": "L0",
            "Ref": "L0",
            "TokenGain": "L0",
            "Handoff": "L1",
            "ResumePacket": "L1",
            "Task": "L2",
        }
        layer = layer_map.get(node_type, "unknown")
        return {
            "node_type": node_type,
            "layer": layer,
            "is_memory_entity": node_type in layer_map,
        }


def annotate_semantic_strength(
    results: List[Dict[str, Any]],
    edge_type_field: str = "edge_type",
) -> List[Dict[str, Any]]:
    """Annotate a list of results with ontology semantic strength.

    For each result, looks up edge_type in EDGE_SEMANTIC_STRENGTH
    and adds `semantic_strength` and `confidence_range` fields.
    """
    for result in results:
        edge_type = result.get(edge_type_field, "")
        if not edge_type:
            # Try to infer from node type
            node_type = result.get("node", {}).get("type", result.get("type", ""))
            category = EntityValidator.classify_entity_category(node_type)
            strength_map = {
                "structural": "fact",
                "declarative": "fact",
                "contractual": "inferred",
                "inferential": "derived",
                "memory": "derived",
            }
            result["semantic_strength"] = strength_map.get(category, "unknown")
        else:
            result["semantic_strength"] = edge_strength(edge_type) if edge_type in ALL_EDGE_TYPES else "unknown"
        # Add confidence range if edge type is known
        if edge_type in EDGE_CONFIDENCE_RANGES:
            result["confidence_range"] = list(EDGE_CONFIDENCE_RANGES[edge_type])
    return results


def multi_hop_confidence(base_confidence: float, hops: int) -> float:
    """Apply multi-hop confidence decay per §4.

    2-hop: ×0.9, 3-hop: ×0.8, 4+ hop: ×0.7
    """
    if hops <= 1:
        return base_confidence
    decay = {2: 0.9, 3: 0.8}.get(hops, 0.7)
    return round(base_confidence * decay, 4)


def confidence_label(confidence: float) -> str:
    """Map numeric confidence to human-readable label.

    Thresholds (aligned with ontology §4):
    - >= 0.8: "high"
    - >= 0.5: "medium"
    - < 0.5: "low"
    """
    if confidence >= 0.8:
        return "high"
    if confidence >= 0.5:
        return "medium"
    return "low"
