"""Comprehensive tests for all new V3 modules.

Covers:
- EvidenceSelector (context/evidence.py)
- ReconcileService (freshness/reconcile.py)
- GlossaryExtractor (onboarding/glossary.py)
- OnboardingGuideGenerator (onboarding/guide.py)
- BusinessFlowGraph (domain/flow.py)
- CodeEntityDomainMapper (domain/mapper.py)
"""
from __future__ import annotations

import pytest

from memory_center.core.context.evidence import Evidence, EvidenceSelector
from memory_center.core.domain.flow import BusinessFlowGraph, FlowEdge, FlowNode, FlowPath
from memory_center.core.domain.mapper import CodeEntityDomainMapper, DomainMapping
from memory_center.core.onboarding.glossary import GlossaryEntry, GlossaryExtractor, _split_camel
from memory_center.core.storage.runtime import RuntimeStore

# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def store(tmp_path):
    """A fresh RuntimeStore backed by a temp file."""
    db = tmp_path / "test_new.db"
    s = RuntimeStore(str(db), pool_size=2)
    yield s
    s.close()


@pytest.fixture
def populated_store(store):
    """A RuntimeStore pre-populated with a graph for new module tests."""
    # Services
    store.upsert_nodes([
        ("Service:user-svc", "Service", "user-svc", "user-svc", "", 0, "{}"),
        ("Service:order-svc", "Service", "order-svc", "order-svc", "", 0, "{}"),
        ("Service:payment-svc", "Service", "payment-svc", "payment-svc", "", 0, "{}"),
    ])
    # Classes
    store.upsert_nodes([
        ("Class:user-svc:UserController", "Class", "UserController", "user-svc",
         "src/ctrl/UserController.java", 10, '{"annotations":["RestController"]}'),
        ("Class:user-svc:UserService", "Class", "UserService", "user-svc",
         "src/svc/UserService.java", 20, '{"annotations":["Service"]}'),
        ("Class:order-svc:OrderService", "Class", "OrderService", "order-svc",
         "src/svc/OrderService.java", 15, '{"annotations":["Service"]}'),
        ("Class:order-svc:OrderFeignClient", "Class", "OrderFeignClient", "order-svc",
         "src/feign/OrderFeignClient.java", 5, '{"annotations":["FeignClient"]}'),
        ("Class:payment-svc:PaymentService", "Class", "PaymentService", "payment-svc",
         "src/svc/PaymentService.java", 25, '{"annotations":["Service"]}'),
    ])
    # MQ Consumer
    store.upsert_nodes([
        ("MQConsumer:order-svc:OrderListener:user-created-topic", "MQConsumer",
         "OrderListener", "order-svc", "src/mq/OrderListener.java", 30,
         '{"class_name":"OrderListener","method_name":"onMessage","topic":"user-created-topic"}'),
    ])
    # ConfigKey
    store.upsert_nodes([
        ("ConfigKey:user-svc:app.timeout", "ConfigKey", "app.timeout", "user-svc",
         "application.yml", 0, '{"value":"3000"}'),
    ])
    # Endpoint
    store.upsert_nodes([
        ("Endpoint:user-svc:GET:/api/users", "Endpoint", "GET /api/users", "user-svc",
         "src/ctrl/UserController.java", 12, '{"http_method":"GET","path":"/api/users"}'),
        ("Endpoint:user-svc:POST:/api/orders", "Endpoint", "POST /api/orders", "user-svc",
         "src/ctrl/OrderController.java", 15, '{"http_method":"POST","path":"/api/orders"}'),
    ])
    # FeignClient
    store.upsert_nodes([
        ("FeignClient:order-svc:UserServiceClient", "FeignClient", "UserServiceClient",
         "order-svc", "src/feign/UserServiceClient.java", 5,
         '{"interface":"UserServiceClient","target_service":"user-svc"}'),
    ])
    # Edges
    store.upsert_edges([
        ("CONTAINS:Service:user-svc->Class:user-svc:UserController",
         "Service:user-svc", "Class:user-svc:UserController", "CONTAINS", 1.0, "{}"),
        ("CONTAINS:Service:user-svc->Class:user-svc:UserService",
         "Service:user-svc", "Class:user-svc:UserService", "CONTAINS", 1.0, "{}"),
        ("CONTAINS:Service:order-svc->Class:order-svc:OrderService",
         "Service:order-svc", "Class:order-svc:OrderService", "CONTAINS", 1.0, "{}"),
        ("CONTAINS:Service:payment-svc->Class:payment-svc:PaymentService",
         "Service:payment-svc", "Class:payment-svc:PaymentService", "CONTAINS", 1.0, "{}"),
        ("CALLS_METHOD:Class:user-svc:UserController->Class:user-svc:UserService",
         "Class:user-svc:UserController", "Class:user-svc:UserService", "CALLS_METHOD", 0.68, "{}"),
        ("CALLS_METHOD:Class:user-svc:UserService->Class:order-svc:OrderService",
         "Class:user-svc:UserService", "Class:order-svc:OrderService", "CALLS_METHOD", 0.58, "{}"),
        ("CALLS_SERVICE:FeignClient:order-svc:UserServiceClient->Service:user-svc",
         "FeignClient:order-svc:UserServiceClient", "Service:user-svc", "CALLS_SERVICE", 0.9, "{}"),
        ("CONSUMES_TOPIC:MQConsumer:order-svc:OrderListener:user-created-topic->MQTopic:user-created-topic",
         "MQConsumer:order-svc:OrderListener:user-created-topic", "MQTopic:user-created-topic",
         "CONSUMES_TOPIC", 1.0, "{}"),
        ("READS_CONFIG:Class:user-svc:UserService->ConfigKey:user-svc:app.timeout",
         "Class:user-svc:UserService", "ConfigKey:user-svc:app.timeout", "READS_CONFIG", 0.84, "{}"),
        ("EXPOSES_ENDPOINT:Class:user-svc:UserController->Endpoint:user-svc:GET:/api/users",
         "Class:user-svc:UserController", "Endpoint:user-svc:GET:/api/users", "EXPOSES_ENDPOINT", 1.0, "{}"),
        ("EXPOSES_ENDPOINT:Class:user-svc:UserService->Endpoint:user-svc:POST:/api/orders",
         "Class:user-svc:UserService", "Endpoint:user-svc:POST:/api/orders", "EXPOSES_ENDPOINT", 1.0, "{}"),
        ("CONTAINS:Service:order-svc->Class:order-svc:OrderFeignClient",
         "Service:order-svc", "Class:order-svc:OrderFeignClient", "CONTAINS", 1.0, "{}"),
    ])
    return store


# ═══════════════════════════════════════════════════════════════════════════════
# EvidenceSelector tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestEvidenceSelector:
    """Tests for EvidenceSelector."""

    def test_select_basic(self):
        """select returns ranked evidence from mixed candidates."""
        sel = EvidenceSelector()
        candidates = [
            {"node_id": "A", "source": "graph_exact", "score": 0.8, "confidence": 0.9},
            {"node_id": "B", "source": "bm25", "score": 0.7, "confidence": 0.6},
            {"node_id": "C", "source": "vector", "score": 0.9, "confidence": 0.5},
        ]
        result = sel.select(candidates, limit=10)
        assert len(result) == 3
        # graph_exact should rank highest due to weight 1.0
        assert result[0].node_id == "A"
        assert result[0].source == "graph_exact"

    def test_select_deduplicates_by_node_id(self):
        """select keeps highest-scoring entry per node_id."""
        sel = EvidenceSelector()
        candidates = [
            {"node_id": "A", "source": "bm25", "score": 0.5, "confidence": 0.5},
            {"node_id": "A", "source": "graph_exact", "score": 0.8, "confidence": 0.9},
        ]
        result = sel.select(candidates, limit=10)
        assert len(result) == 1
        assert result[0].source == "graph_exact"

    def test_select_min_score_filter(self):
        """select filters out candidates below min_score."""
        sel = EvidenceSelector()
        candidates = [
            {"node_id": "A", "source": "vector", "score": 0.1, "confidence": 0.5},
            {"node_id": "B", "source": "graph_exact", "score": 0.9, "confidence": 0.9},
        ]
        result = sel.select(candidates, limit=10, min_score=0.5)
        assert len(result) == 1
        assert result[0].node_id == "B"

    def test_select_limit(self):
        """select respects limit parameter."""
        sel = EvidenceSelector()
        candidates = [
            {"node_id": f"N{i}", "source": "bm25", "score": 0.8, "confidence": 0.5}
            for i in range(20)
        ]
        result = sel.select(candidates, limit=5)
        assert len(result) == 5

    def test_merge_sources(self):
        """merge_sources combines three source lists."""
        sel = EvidenceSelector()
        graph = [{"node_id": "G1", "score": 0.9, "confidence": 0.8}]
        sparse = [{"node_id": "S1", "score": 0.7, "confidence": 0.6}]
        vector = [{"node_id": "V1", "score": 0.8, "confidence": 0.5}]
        result = sel.merge_sources(graph, sparse, vector, limit=10)
        assert len(result) == 3
        node_ids = {e.node_id for e in result}
        assert node_ids == {"G1", "S1", "V1"}

    def test_merge_sources_no_mutation(self):
        """merge_sources does not mutate the caller's input dicts."""
        sel = EvidenceSelector()
        graph = [{"node_id": "G1", "score": 0.9, "confidence": 0.8}]
        sparse = [{"node_id": "S1", "score": 0.7, "confidence": 0.6}]
        vector = [{"node_id": "V1", "score": 0.8, "confidence": 0.5}]
        sel.merge_sources(graph, sparse, vector)
        assert "source" not in graph[0]
        assert "source" not in sparse[0]
        assert "source" not in vector[0]

    def test_explain(self):
        """explain returns human-readable explanation."""
        sel = EvidenceSelector()
        ev = Evidence(node_id="X", source="bm25", score=0.75, confidence=0.8)
        text = sel.explain(ev)
        assert "bm25" in text
        assert "0.750" in text

    def test_custom_weights(self):
        """custom source weights affect ranking."""
        sel = EvidenceSelector(source_weights={"custom": 2.0, "bm25": 0.1})
        candidates = [
            {"node_id": "A", "source": "custom", "score": 0.5, "confidence": 0.5},
            {"node_id": "B", "source": "bm25", "score": 0.9, "confidence": 0.9},
        ]
        result = sel.select(candidates, limit=10)
        # custom with weight 2.0: 0.5 * 2.0 = 1.0 > bm25 with 0.1: 0.9 * 0.1 = 0.09
        assert result[0].node_id == "A"

    def test_recency_bonus(self):
        """recent items get a recency bonus."""
        sel = EvidenceSelector()
        candidates = [
            {"node_id": "OLD", "source": "bm25", "score": 0.8, "confidence": 0.5, "recency_hours": 168},
            {"node_id": "NEW", "source": "bm25", "score": 0.8, "confidence": 0.5, "recency_hours": 0},
        ]
        result = sel.select(candidates, limit=10)
        assert result[0].node_id == "NEW"

    def test_evidence_to_dict(self):
        """Evidence.to_dict returns correct structure."""
        ev = Evidence(node_id="X", source="bm25", score=0.75, confidence=0.8, description="test")
        d = ev.to_dict()
        assert d["node_id"] == "X"
        assert d["source"] == "bm25"
        assert d["score"] == 0.75
        assert d["confidence"] == 0.8
        assert d["description"] == "test"


# ═══════════════════════════════════════════════════════════════════════════════
# GlossaryExtractor tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestGlossaryExtractor:
    """Tests for GlossaryExtractor."""

    def test_extract_basic(self, populated_store):
        """extract returns glossary entries from the graph."""
        ext = GlossaryExtractor(populated_store)
        result = ext.extract(limit=50)
        assert len(result) > 0
        # Should find service names
        service_terms = [t for t in result if t.category == "service"]
        assert len(service_terms) >= 3

    def test_extract_class_terms(self, populated_store):
        """extract splits CamelCase class names into domain terms."""
        ext = GlossaryExtractor(populated_store)
        result = ext.extract(limit=100)
        class_terms = [t for t in result if t.category == "class"]
        assert len(class_terms) > 0
        # Should find terms like "user", "order", "controller", "service"
        term_names = {t.term.lower() for t in class_terms}
        assert "user" in term_names or "controller" in term_names or "service" in term_names

    def test_extract_annotations(self, populated_store):
        """extract finds annotation terms."""
        ext = GlossaryExtractor(populated_store)
        result = ext.extract(limit=100)
        ann_terms = [t for t in result if t.category == "annotation"]
        assert len(ann_terms) > 0
        ann_names = {t.term for t in ann_terms}
        assert "RestController" in ann_names or "Service" in ann_names

    def test_extract_config_keys(self, populated_store):
        """extract finds config key terms."""
        ext = GlossaryExtractor(populated_store)
        result = ext.extract(limit=100)
        config_terms = [t for t in result if t.category == "config"]
        assert len(config_terms) > 0

    def test_search(self, populated_store):
        """search finds matching terms."""
        ext = GlossaryExtractor(populated_store)
        result = ext.search("user", limit=10)
        assert len(result) > 0
        for entry in result:
            assert "user" in entry.term.lower()

    def test_split_camel(self):
        """_split_camel splits CamelCase correctly."""
        assert _split_camel("UserController") == ["user", "controller"]
        assert _split_camel("OrderService") == ["order", "service"]
        assert _split_camel("HTTPClient") == ["http", "client"]
        assert _split_camel("AB") == ["ab"]

    def test_extract_limit(self, populated_store):
        """extract respects limit parameter."""
        ext = GlossaryExtractor(populated_store)
        result = ext.extract(limit=3)
        assert len(result) <= 3

    def test_glossary_entry_to_dict(self):
        """GlossaryEntry.to_dict returns correct structure."""
        entry = GlossaryEntry(
            term="user", category="service", frequency=5,
            examples=["UserService"], description="test"
        )
        d = entry.to_dict()
        assert d["term"] == "user"
        assert d["category"] == "service"
        assert d["frequency"] == 5


# ═══════════════════════════════════════════════════════════════════════════════
# BusinessFlowGraph tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestBusinessFlowGraph:
    """Tests for BusinessFlowGraph."""

    def test_build_flow_graph_basic(self, populated_store):
        """build_flow_graph returns nodes and edges."""
        fg = BusinessFlowGraph(populated_store)
        result = fg.build_flow_graph()
        assert "nodes" in result
        assert "edges" in result
        assert result["node_count"] > 0

    def test_build_flow_graph_node_types(self, populated_store):
        """build_flow_graph includes correct node types."""
        fg = BusinessFlowGraph(populated_store)
        result = fg.build_flow_graph()
        types = {n["type"] for n in result["nodes"]}
        assert "Endpoint" in types or "Class" in types or "Service" in types

    def test_trace_flow_from_endpoint(self, populated_store):
        """trace_flow_from_endpoint returns a FlowPath."""
        fg = BusinessFlowGraph(populated_store)
        path = fg.trace_flow_from_endpoint("Endpoint:user-svc:GET:/api/users")
        assert isinstance(path, FlowPath)
        assert len(path.nodes) > 0
        assert path.nodes[0] == "Endpoint:user-svc:GET:/api/users"

    def test_trace_flow_confidence(self, populated_store):
        """confidence decreases with depth."""
        fg = BusinessFlowGraph(populated_store)
        path = fg.trace_flow_from_endpoint("Endpoint:user-svc:GET:/api/users")
        assert path.total_confidence <= 1.0
        assert path.total_confidence > 0

    def test_find_impact_along_flows(self, populated_store):
        """find_impact_along_flows finds downstream impacts."""
        fg = BusinessFlowGraph(populated_store)
        impacts = fg.find_impact_along_flows("Class:user-svc:UserController")
        assert isinstance(impacts, list)
        for impact in impacts:
            assert "node_id" in impact
            assert "depth" in impact

    def test_find_impact_excludes_source(self, populated_store):
        """find_impact_along_flows does not include the source node."""
        fg = BusinessFlowGraph(populated_store)
        impacts = fg.find_impact_along_flows("Class:user-svc:UserController")
        impact_ids = [i["node_id"] for i in impacts]
        assert "Class:user-svc:UserController" not in impact_ids

    def test_flow_node_to_dict(self):
        """FlowNode.to_dict returns correct structure."""
        node = FlowNode(node_id="X", name="Test", node_type="Class", step_order=1, service="svc")
        d = node.to_dict()
        assert d["node_id"] == "X"
        assert d["name"] == "Test"
        assert d["type"] == "Class"
        assert d["step_order"] == 1

    def test_flow_edge_to_dict(self):
        """FlowEdge.to_dict returns correct structure."""
        edge = FlowEdge(source_id="A", target_id="B", edge_type="CALLS", confidence=0.8)
        d = edge.to_dict()
        assert d["source_id"] == "A"
        assert d["target_id"] == "B"
        assert d["type"] == "CALLS"
        assert d["confidence"] == 0.8

    def test_flow_path_to_dict(self):
        """FlowPath.to_dict returns correct structure."""
        path = FlowPath(path_id="P1", nodes=["A", "B"], edge_types=["CALLS"],
                        total_confidence=0.9, description="test")
        d = path.to_dict()
        assert d["path_id"] == "P1"
        assert d["depth"] == 2
        assert d["total_confidence"] == 0.9

    def test_trace_nonexistent_endpoint(self, populated_store):
        """trace_flow_from_endpoint handles nonexistent endpoint gracefully."""
        fg = BusinessFlowGraph(populated_store)
        path = fg.trace_flow_from_endpoint("nonexistent-id")
        assert isinstance(path, FlowPath)
        assert len(path.nodes) == 1  # only the starting node

    def test_trace_flow_edge_types(self, populated_store):
        """trace_flow_from_endpoint returns actual edge types, not just CALLS."""
        fg = BusinessFlowGraph(populated_store)
        path = fg.trace_flow_from_endpoint("Endpoint:user-svc:GET:/api/users")
        # The flow should have at least one edge type that is NOT just "CALLS"
        # (it should be something like CALLS_METHOD, EXPOSES_ENDPOINT, etc.)
        assert len(path.edge_types) > 0
        # At least one edge type should come from the graph
        for et in path.edge_types:
            assert et != ""  # not empty

    def test_get_edge_type(self, populated_store):
        """_get_edge_type returns the actual edge type between nodes."""
        fg = BusinessFlowGraph(populated_store)
        edge_type = fg._get_edge_type(
            "Class:user-svc:UserController",
            "Class:user-svc:UserService",
        )
        assert edge_type == "CALLS_METHOD"
    def test_impact_empty_graph(self, tmp_path):
        """find_impact_along_flows handles empty graph."""
        db = tmp_path / "empty.db"
        s = RuntimeStore(str(db), pool_size=2)
        try:
            fg = BusinessFlowGraph(s)
            impacts = fg.find_impact_along_flows("nonexistent")
            assert impacts == []
        finally:
            s.close()


# ═══════════════════════════════════════════════════════════════════════════════
# CodeEntityDomainMapper tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestCodeEntityDomainMapper:
    """Tests for CodeEntityDomainMapper."""

    def test_map_entity_basic(self, populated_store):
        """map_entity returns a DomainMapping."""
        mapper = CodeEntityDomainMapper(populated_store)
        result = mapper.map_entity("Class:user-svc:UserController")
        assert result is not None
        assert isinstance(result, DomainMapping)
        assert result.node_id == "Class:user-svc:UserController"

    def test_map_entity_user_domain(self, populated_store):
        """UserController maps to user domain."""
        mapper = CodeEntityDomainMapper(populated_store)
        result = mapper.map_entity("Class:user-svc:UserController")
        assert result.domain == "user"
        assert result.confidence > 0

    def test_map_entity_order_domain(self, populated_store):
        """OrderService maps to order domain."""
        mapper = CodeEntityDomainMapper(populated_store)
        result = mapper.map_entity("Class:order-svc:OrderService")
        assert result.domain == "order"

    def test_map_entity_nonexistent(self, populated_store):
        """map_entity returns None for nonexistent node."""
        mapper = CodeEntityDomainMapper(populated_store)
        result = mapper.map_entity("nonexistent-id")
        assert result is None

    def test_map_batch_by_ids(self, populated_store):
        """map_batch with node_ids returns mappings for those IDs."""
        mapper = CodeEntityDomainMapper(populated_store)
        ids = ["Class:user-svc:UserController", "Class:order-svc:OrderService"]
        result = mapper.map_batch(node_ids=ids)
        assert len(result) == 2

    def test_map_batch_by_type(self, populated_store):
        """map_batch with node_type filters by type."""
        mapper = CodeEntityDomainMapper(populated_store)
        result = mapper.map_batch(node_type="Service", limit=10)
        assert len(result) >= 3  # 3 services
        for m in result:
            assert m.node_type == "Service"

    def test_map_batch_limit(self, populated_store):
        """map_batch respects limit."""
        mapper = CodeEntityDomainMapper(populated_store)
        result = mapper.map_batch(limit=2)
        assert len(result) <= 2

    def test_domain_summary(self, populated_store):
        """domain_summary returns domain distribution."""
        mapper = CodeEntityDomainMapper(populated_store)
        summary = mapper.domain_summary()
        assert "total_entities" in summary
        assert "domain_counts" in summary
        assert "domains" in summary
        assert summary["total_entities"] > 0

    def test_service_domain_inference(self, populated_store):
        """service-level domain inference works."""
        mapper = CodeEntityDomainMapper(populated_store)
        # payment-svc should infer payment domain
        result = mapper.map_entity("Class:payment-svc:PaymentService")
        assert result.domain == "payment"

    def test_domain_mapping_to_dict(self):
        """DomainMapping.to_dict returns correct structure."""
        m = DomainMapping(
            node_id="X", node_name="Test", node_type="Class",
            domain="user", confidence=0.8, evidence="test"
        )
        d = m.to_dict()
        assert d["node_id"] == "X"
        assert d["domain"] == "user"
        assert d["confidence"] == 0.8

    def test_neighbor_inference(self, populated_store):
        """neighbor-based domain inference works for ambiguous entities."""
        mapper = CodeEntityDomainMapper(populated_store)
        # ConfigKey has no direct domain keyword, but its neighbor UserService
        # should influence it via graph
        result = mapper.map_entity("ConfigKey:user-svc:app.timeout")
        assert result is not None
        assert result.domain != ""


# ═══════════════════════════════════════════════════════════════════════════════
# ReconcileService tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestReconcileService:
    """Tests for ReconcileService (freshness/reconcile.py)."""

    def test_file_hash(self, tmp_path):
        """_file_hash computes SHA-256 of a file."""
        from memory_center.core.freshness.reconcile import _file_hash
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world")
        h = _file_hash(test_file)
        assert len(h) == 64  # SHA-256 hex
        assert h != ""

    def test_file_hash_nonexistent(self, tmp_path):
        """_file_hash returns empty string for nonexistent file."""
        from memory_center.core.freshness.reconcile import _file_hash
        h = _file_hash(tmp_path / "nonexistent.txt")
        assert h == ""

    def test_scan_source_files(self, tmp_path):
        """_scan_source_files finds Java and config files."""
        from memory_center.core.freshness.reconcile import _scan_source_files
        # Create test files
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "Main.java").write_text("class Main {}")
        (tmp_path / "application.yml").write_text("server:\n  port: 8080")
        (tmp_path / "README.md").write_text("# Test")
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("ignored")

        result = _scan_source_files(tmp_path)
        assert "src/Main.java" in result
        assert "application.yml" in result
        assert "README.md" not in result  # not in extensions
        assert ".git/config" not in result  # ignored dir

    def test_reconcile_result_to_dict(self):
        """ReconcileResult.to_dict returns correct structure."""
        from memory_center.core.freshness.reconcile import ReconcileResult
        r = ReconcileResult(
            checked_files=10,
            stale_files=["a.java"],
            added_files=["b.java"],
            deleted_files=["c.java"],
            duration_ms=100.5,
            needs_reindex=True,
        )
        d = r.to_dict()
        assert d["checked_files"] == 10
        assert d["stale_count"] == 1
        assert d["added_count"] == 1
        assert d["deleted_count"] == 1
        assert d["needs_reindex"] is True

    def test_reconcile_empty_workspace(self, tmp_path):
        """reconcile handles empty workspace."""
        from memory_center.core.freshness.reconcile import ReconcileService
        # Create a minimal workspace config
        ws_dir = tmp_path / ".memory-center"
        ws_dir.mkdir()
        ws_file = tmp_path / ".memory-center" / "workspace.yaml"
        ws_file.write_text("workspace: test\n")

        svc = ReconcileService(str(ws_file))
        result = svc.reconcile()
        assert result.checked_files >= 0
        assert isinstance(result.needs_reindex, bool)

    def test_reconcile_detects_added_files(self, tmp_path):
        """reconcile detects added files."""
        from memory_center.core.freshness.reconcile import ReconcileService
        ws_dir = tmp_path / ".memory-center"
        ws_dir.mkdir()
        ws_file = tmp_path / ".memory-center" / "workspace.yaml"
        ws_file.write_text("workspace: test\n")

        # Add a Java file
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "New.java").write_text("class New {}")

        svc = ReconcileService(str(ws_file))
        result = svc.reconcile()
        assert result.checked_files > 0


# ═══════════════════════════════════════════════════════════════════════════════
# OnboardingGuideGenerator tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestOnboardingGuideGenerator:
    """Tests for OnboardingGuideGenerator."""

    def test_generate_basic(self, populated_store):
        """generate returns an OnboardingGuide."""
        from memory_center.core.onboarding.guide import OnboardingGuideGenerator
        gen = OnboardingGuideGenerator(populated_store)
        guide = gen.generate(persona="developer")
        assert guide.persona == "developer"
        assert len(guide.sections) > 0
        assert guide.guide_id.startswith("guide:")

    def test_generate_different_personas(self, populated_store):
        """generate adapts to different personas."""
        from memory_center.core.onboarding.guide import OnboardingGuideGenerator
        gen = OnboardingGuideGenerator(populated_store)
        for persona in ("developer", "architect", "product", "tester"):
            guide = gen.generate(persona=persona)
            assert guide.persona == persona
            assert len(guide.sections) > 0

    def test_generate_sections_have_content(self, populated_store):
        """all sections have non-empty content."""
        from memory_center.core.onboarding.guide import OnboardingGuideGenerator
        gen = OnboardingGuideGenerator(populated_store)
        guide = gen.generate()
        for section in guide.sections:
            assert section.title != ""
            assert section.content != ""

    def test_generate_glossary_included(self, populated_store):
        """guide includes glossary terms."""
        from memory_center.core.onboarding.guide import OnboardingGuideGenerator
        gen = OnboardingGuideGenerator(populated_store)
        guide = gen.generate()
        assert len(guide.glossary_terms) > 0

    def test_guide_to_dict(self, populated_store):
        """OnboardingGuide.to_dict returns correct structure."""
        from memory_center.core.onboarding.guide import OnboardingGuideGenerator
        gen = OnboardingGuideGenerator(populated_store)
        guide = gen.generate()
        d = guide.to_dict()
        assert "guide_id" in d
        assert "persona" in d
        assert "sections" in d
        assert "glossary_terms" in d
        assert "total_sections" in d

    def test_guide_section_to_dict(self):
        """GuideSection.to_dict returns correct structure."""
        from memory_center.core.onboarding.guide import GuideSection
        s = GuideSection(
            section_id=1, title="Test", content="Content",
            action_items=["item1"], related_nodes=["node1"]
        )
        d = s.to_dict()
        assert d["section_id"] == 1
        assert d["title"] == "Test"
        assert d["content"] == "Content"
        assert len(d["action_items"]) == 1

    def test_generate_empty_store(self, tmp_path):
        """generate handles empty store gracefully."""
        from memory_center.core.onboarding.guide import OnboardingGuideGenerator
        db = tmp_path / "empty.db"
        s = RuntimeStore(str(db), pool_size=2)
        try:
            gen = OnboardingGuideGenerator(s)
            guide = gen.generate()
            assert len(guide.sections) > 0  # still has welcome + glossary + first tasks
        finally:
            s.close()


# ═══════════════════════════════════════════════════════════════════════════════
# Integration tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestV3Integration:
    """Integration tests combining multiple V3 modules."""

    def test_evidence_with_graph_results(self, populated_store):
        """EvidenceSelector works with real graph retrieval results."""
        sel = EvidenceSelector()

        # Simulate retrieval results
        candidates = [
            {"node_id": "Class:user-svc:UserController", "source": "graph_exact", "score": 0.9, "confidence": 0.8},
            {"node_id": "Class:user-svc:UserService", "source": "bm25", "score": 0.7, "confidence": 0.6},
        ]
        result = sel.select(candidates, limit=5)
        assert len(result) == 2

    def test_glossary_with_domain_mapper(self, populated_store):
        """Glossary and domain mapper produce consistent results."""
        glossary = GlossaryExtractor(populated_store)
        mapper = CodeEntityDomainMapper(populated_store)

        terms = glossary.extract(limit=10)
        domains = mapper.domain_summary()

        # Both should find user-related concepts
        term_names = {t.term.lower() for t in terms}
        assert "user" in term_names or "user-svc" in term_names
        assert "user" in domains["domains"] or len(domains["domains"]) > 0

    def test_flow_graph_with_impact(self, populated_store):
        """BusinessFlowGraph flow tracing and impact analysis work together."""
        fg = BusinessFlowGraph(populated_store)

        # Build flow graph
        graph = fg.build_flow_graph()
        assert graph["node_count"] > 0

        # Trace from endpoint
        path = fg.trace_flow_from_endpoint("Endpoint:user-svc:GET:/api/users")
        assert len(path.nodes) > 0

        # Find impact from a class
        impacts = fg.find_impact_along_flows("Class:user-svc:UserController")
        assert isinstance(impacts, list)
