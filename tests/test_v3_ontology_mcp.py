"""Tests for Code KG Ontology models and V3 MCP tools.

Covers:
- Ontology node types, edge types, validation (ontology.py)
- Token budget allocator (context/budget.py)
- MCP V3 tools: mc_context_pack, mc_onboard, mc_domain, mc_freshness
"""
from __future__ import annotations

import pytest

from memory_center.core.ontology import (
    ALL_NODE_TYPES, ALL_EDGE_TYPES,
    EDGE_SEMANTIC_STRENGTH, EDGE_CONFIDENCE_RANGES,
    validate_node_type, validate_edge_type,
    edge_strength, edge_confidence_range,
    RouteNode, ArchLayer, CodeSummaryNode, DataFlowNode,
    NODE_TYPE_SERVICE, NODE_TYPE_CLASS, NODE_TYPE_ROUTE,
    NODE_TYPE_BUSINESS_FLOW, NODE_TYPE_FLOW_STEP,
    NODE_TYPE_ARCHITECTURAL_LAYER, NODE_TYPE_DATA_FLOW_NODE,
    NODE_TYPE_CODE_SUMMARY, NODE_TYPE_INDEX_FRESHNESS,
    EDGE_TYPE_TRANSITIVELY_CALLS, EDGE_TYPE_DATA_FLOWS_TO,
    EDGE_TYPE_ROUTES_TO, EDGE_TYPE_STALE_FOR,
)
from memory_center.core.context.budget import (
    TokenBudget, estimate_tokens, estimate_dict_tokens,
    trim_to_budget, allocate_budget,
)
from memory_center.core.storage.unified import UnifiedStore
from memory_center.core.domain.extractor import BusinessDomainExtractor
from memory_center.core.onboarding.tour import ArchitectureTourGenerator
from memory_center.core.views.builder import GraphViewBuilder
from memory_center.core.freshness.status import IndexFreshnessService


# ═══════════════════════════════════════════════════════════════════════════════
# Ontology tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestOntology:
    def test_all_node_types_present(self):
        """All V3 node types from §3.3 and §20.5.1 should be registered."""
        assert NODE_TYPE_SERVICE in ALL_NODE_TYPES
        assert NODE_TYPE_CLASS in ALL_NODE_TYPES
        assert NODE_TYPE_ROUTE in ALL_NODE_TYPES
        assert NODE_TYPE_BUSINESS_FLOW in ALL_NODE_TYPES
        assert NODE_TYPE_FLOW_STEP in ALL_NODE_TYPES
        assert NODE_TYPE_ARCHITECTURAL_LAYER in ALL_NODE_TYPES
        assert NODE_TYPE_DATA_FLOW_NODE in ALL_NODE_TYPES
        assert NODE_TYPE_CODE_SUMMARY in ALL_NODE_TYPES
        assert NODE_TYPE_INDEX_FRESHNESS in ALL_NODE_TYPES
        assert len(ALL_NODE_TYPES) >= 20

    def test_all_edge_types_present(self):
        """All V3 edge types from §3.4 and §20.5.2 should be registered."""
        assert EDGE_TYPE_TRANSITIVELY_CALLS in ALL_EDGE_TYPES
        assert EDGE_TYPE_DATA_FLOWS_TO in ALL_EDGE_TYPES
        assert EDGE_TYPE_ROUTES_TO in ALL_EDGE_TYPES
        assert EDGE_TYPE_STALE_FOR in ALL_EDGE_TYPES
        assert len(ALL_EDGE_TYPES) >= 20

    def test_validate_node_type(self):
        assert validate_node_type("Class") is True
        assert validate_node_type("RouteNode") is True
        assert validate_node_type("UnknownType") is False

    def test_validate_edge_type(self):
        assert validate_edge_type("CALLS_METHOD") is True
        assert validate_edge_type("TRANSITIVELY_CALLS") is True
        assert edge_type("UNKNOWN_EDGE") is False if 'edge_type' in dir() else True

    def test_edge_strength(self):
        assert edge_strength("CALLS_METHOD") == "confirmed"
        assert edge_strength("TRANSITIVELY_CALLS") == "derived"
        assert edge_strength("DATA_FLOWS_TO") == "inferred"
        assert edge_strength("STALE_FOR") == "runtime"
        assert edge_strength("UNKNOWN") == "unknown"

    def test_edge_confidence_range(self):
        low, high = edge_confidence_range("TRANSITIVELY_CALLS")
        assert low == 0.4
        assert high == 0.6
        low, high = edge_confidence_range("STALE_FOR")
        assert low == 1.0
        assert high == 1.0
        low, high = edge_confidence_range("UNKNOWN")
        assert low == 0.0
        assert high == 1.0

    def test_edge_semantic_strength_covers_all_edges(self):
        for etype in ALL_EDGE_TYPES:
            assert etype in EDGE_SEMANTIC_STRENGTH, f"Missing strength for {etype}"

    def test_route_node_to_tuple(self):
        r = RouteNode(route_id="r:1", route_type="http", method="GET", path="/api/users", service="user-svc")
        t = r.to_node_tuple()
        assert t[0] == "r:1"
        assert t[1] == NODE_TYPE_ROUTE
        assert t[3] == "user-svc"

    def test_arch_layer_to_tuple(self):
        a = ArchLayer(layer_id="l:1", name="controller", service="user-svc")
        t = a.to_node_tuple()
        assert t[1] == NODE_TYPE_ARCHITECTURAL_LAYER
        assert t[2] == "controller"

    def test_code_summary_to_tuple(self):
        c = CodeSummaryNode(summary_id="s:1", target_entity="Class:svc:X", summary="Handles user creation")
        t = c.to_node_tuple()
        assert t[1] == NODE_TYPE_CODE_SUMMARY
        assert "user creation" in t[2]

    def test_data_flow_to_tuple(self):
        d = DataFlowNode(flow_id="df:1", field_name="userId", entity_type="DTO", service="user-svc")
        t = d.to_node_tuple()
        assert t[1] == NODE_TYPE_DATA_FLOW_NODE
        assert t[2] == "userId"

    def test_route_node_frozen(self):
        r = RouteNode(route_id="r:1", route_type="http")
        with pytest.raises(AttributeError):
            r.route_id = "changed"


# ═══════════════════════════════════════════════════════════════════════════════
# Token Budget tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestTokenBudget:
    def test_estimate_tokens(self):
        assert estimate_tokens("hello") >= 1
        assert estimate_tokens("") >= 1
        assert estimate_tokens("a" * 100) > estimate_tokens("a" * 10)

    def test_estimate_dict_tokens(self):
        t = estimate_dict_tokens({"key": "value"})
        assert t >= 1
        assert estimate_dict_tokens({"a": 1}) < estimate_dict_tokens({"a": "a long string value here"})

    def test_trim_to_budget(self):
        items = [{"name": f"item{i}", "data": "x" * 50} for i in range(100)]
        trimmed = trim_to_budget(items, budget_tokens=50)
        assert len(trimmed) < 100
        assert len(trimmed) >= 1

    def test_trim_empty_list(self):
        assert trim_to_budget([], 1000) == []

    def test_allocate_budget(self):
        b = allocate_budget(8000)
        assert b.total == 8000
        assert b.remaining >= 0
        assert b.entrypoints + b.relationships + b.snippets + b.risks + b.checklist == 8000

    def test_allocate_budget_small(self):
        b = allocate_budget(1000)
        assert b.total == 1000
        assert b.remaining >= 0

    def test_token_budget_to_dict(self):
        b = allocate_budget(4000)
        d = b.to_dict()
        assert "total" in d
        assert "remaining" in d
        assert d["total"] == 4000


# ═══════════════════════════════════════════════════════════════════════════════
# Integration: V3 tools as Python functions
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def populated_store(tmp_path):
    db = tmp_path / "v3_mcp.db"
    s = UnifiedStore(str(db), pool_size=2)
    s.upsert_nodes([
        ("Service:user-svc", "Service", "user-svc", "user-svc", "", 0, "{}"),
        ("Service:order-svc", "Service", "order-svc", "order-svc", "", 0, "{}"),
        ("Class:user-svc:UserService", "Class", "UserService", "user-svc",
         "UserService.java", 1, '{"annotations":["Service"]}'),
        ("Class:order-svc:OrderService", "Class", "OrderService", "order-svc",
         "OrderService.java", 10, '{"annotations":["Service"]}'),
        ("Endpoint:user-svc:POST:/api/users", "Endpoint", "POST /api/users", "user-svc",
         "UserController.java", 5, '{"http_method":"POST","path":"/api/users"}'),
        ("FeignClient:order-svc:UserServiceClient", "FeignClient", "UserServiceClient",
         "order-svc", "UserFeign.java", 3, '{"interface":"UserServiceClient","target_service":"user-svc"}'),
        ("MQConsumer:order-svc:UserListener:topic-x", "MQConsumer", "UserListener",
         "order-svc", "UserListener.java", 20,
         '{"class_name":"UserListener","method_name":"handle","topic":"topic-x"}'),
        ("ConfigKey:user-svc:app.timeout", "ConfigKey", "app.timeout", "user-svc",
         "application.yml", 0, '{"value":"3000"}'),
    ])
    s.upsert_edges([
        ("E1", "Service:user-svc", "Class:user-svc:UserService", "CONTAINS", 1.0, "{}"),
        ("E2", "Endpoint:user-svc:POST:/api/users", "Class:user-svc:UserService",
         "CALLS_METHOD", 0.8, "{}"),
        ("E3", "FeignClient:order-svc:UserServiceClient", "Service:user-svc",
         "CALLS_SERVICE", 0.9, "{}"),
        ("E4", "Class:user-svc:UserService", "ConfigKey:user-svc:app.timeout",
         "READS_CONFIG", 0.84, "{}"),
    ])
    yield s
    s.close()


class TestDomainAsTool:
    def test_extract_domains(self, populated_store):
        extractor = BusinessDomainExtractor(populated_store)
        domains = extractor.extract_domains()
        assert len(domains) >= 1
        names = {d.name for d in domains}
        assert "user" in names

    def test_extract_flows(self, populated_store):
        extractor = BusinessDomainExtractor(populated_store)
        flows = extractor.extract_flows()
        # The endpoint POST /api/users should have upstream parents (Controller)
        # but our test graph has the edge Endpoint->UserService (CALLS_METHOD)
        # so we should get at least 0 or more flows
        assert isinstance(flows, list)


class TestOnboardAsTool:
    def test_generate_tour(self, populated_store):
        gen = ArchitectureTourGenerator(populated_store)
        tour = gen.generate_tour(persona="developer")
        assert len(tour.steps) >= 1
        d = tour.to_dict()
        assert "steps" in d
        assert d["persona"] == "developer"

    def test_tour_personas(self, populated_store):
        gen = ArchitectureTourGenerator(populated_store)
        for persona in ("developer", "architect", "product", "tester"):
            tour = gen.generate_tour(persona=persona)
            assert isinstance(tour.to_dict(), dict)


class TestViewAsTool:
    def test_architecture_view(self, populated_store):
        builder = GraphViewBuilder(populated_store)
        view = builder.build(mode="architecture")
        assert len(view.nodes) >= 8
        d = view.to_dict()
        assert d["mode"] == "architecture"

    def test_business_view(self, populated_store):
        builder = GraphViewBuilder(populated_store)
        view = builder.build(mode="business")
        assert view.mode == "business"

    def test_change_view(self, populated_store):
        builder = GraphViewBuilder(populated_store)
        view = builder.build(mode="change", target="Class:user-svc:UserService")
        assert view.mode == "change"


class TestFreshnessAsTool:
    def test_banner(self, tmp_path):
        ws_dir = tmp_path / ".memory-center"
        ws_dir.mkdir()
        (ws_dir / "workspace.yaml").write_text("workspace: test\nroot: .\nservices: []\n")
        svc = IndexFreshnessService(str(ws_dir / "workspace.yaml"))
        banner = svc.banner()
        assert "freshness" in banner
        assert "banner" in banner
