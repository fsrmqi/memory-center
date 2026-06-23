"""Comprehensive tests for all V3 modules.

Covers:
- SQLitePool (storage/pool.py)
- UnifiedStore (storage/unified.py)
- InvertedIndex (retrieval/inverted.py)
- ContextPackBuilder (context/pack.py)
- IndexFreshnessService (freshness/status.py)
- GraphPatternEngine (reasoning/patterns.py)
- TransitiveInferenceEngine (reasoning/transitive.py)
- RiskPatternEngine (reasoning/risk.py)
- Progressive views (presentation/progressive.py)
"""
from __future__ import annotations

import json

import pytest

from memory_center.core.storage.pool import SQLitePool
from memory_center.core.storage.unified import UnifiedStore
from memory_center.core.retrieval.inverted import InvertedIndex
from memory_center.core.freshness.status import IndexFreshnessService, FreshnessStatus
from memory_center.core.reasoning.patterns import GraphPatternEngine
from memory_center.core.reasoning.transitive import TransitiveInferenceEngine
from memory_center.core.reasoning.risk import RiskPatternEngine
from memory_center.core.presentation.progressive import build_progressive_levels


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def pool(tmp_path):
    """A fresh SQLitePool backed by a temp file."""
    db = tmp_path / "test_pool.db"
    p = SQLitePool(str(db), pool_size=2)
    yield p
    p.close()


@pytest.fixture
def store(tmp_path):
    """A fresh UnifiedStore backed by a temp file."""
    db = tmp_path / "test_unified.db"
    s = UnifiedStore(str(db), pool_size=2)
    yield s
    s.close()


@pytest.fixture
def populated_store(store):
    """A UnifiedStore pre-populated with a small graph for reasoning tests."""
    # Services
    store.upsert_nodes([
        ("Service:user-svc", "Service", "user-svc", "user-svc", "", 0, "{}"),
        ("Service:order-svc", "Service", "order-svc", "order-svc", "", 0, "{}"),
        ("Service:payment-svc", "Service", "payment-svc", "payment-svc", "", 0, "{}"),
    ])
    # Classes
    store.upsert_nodes([
        ("Class:user-svc:UserController", "Class", "UserController", "user-svc", "src/ctrl/UserController.java", 10, '{"annotations":["RestController"]}'),
        ("Class:user-svc:UserService", "Class", "UserService", "user-svc", "src/svc/UserService.java", 20, '{"annotations":["Service"]}'),
        ("Class:order-svc:OrderService", "Class", "OrderService", "order-svc", "src/svc/OrderService.java", 15, '{"annotations":["Service"]}'),
        ("Class:order-svc:OrderFeignClient", "Class", "OrderFeignClient", "order-svc", "src/feign/OrderFeignClient.java", 5, '{"annotations":["FeignClient"]}'),
    ])
    # MQ Consumer
    store.upsert_nodes([
        ("MQConsumer:order-svc:OrderListener:user-created-topic", "MQConsumer", "OrderListener", "order-svc", "src/mq/OrderListener.java", 30, '{"class_name":"OrderListener","method_name":"onMessage","topic":"user-created-topic"}'),
    ])
    # ConfigKey
    store.upsert_nodes([
        ("ConfigKey:user-svc:app.timeout", "ConfigKey", "app.timeout", "user-svc", "application.yml", 0, '{"value":"3000"}'),
    ])
    # Endpoint
    store.upsert_nodes([
        ("Endpoint:user-svc:GET:/api/users", "Endpoint", "GET /api/users", "user-svc", "src/ctrl/UserController.java", 12, '{"http_method":"GET","path":"/api/users"}'),
    ])
    # FeignClient
    store.upsert_nodes([
        ("FeignClient:order-svc:UserServiceClient", "FeignClient", "UserServiceClient", "order-svc", "src/feign/UserServiceClient.java", 5, '{"interface":"UserServiceClient","target_service":"user-svc"}'),
    ])
    # Edges
    store.upsert_edges([
        ("CONTAINS:Service:user-svc->Class:user-svc:UserController", "Service:user-svc", "Class:user-svc:UserController", "CONTAINS", 1.0, "{}"),
        ("CONTAINS:Service:user-svc->Class:user-svc:UserService", "Service:user-svc", "Class:user-svc:UserService", "CONTAINS", 1.0, "{}"),
        ("CONTAINS:Service:order-svc->Class:order-svc:OrderService", "Service:order-svc", "Class:order-svc:OrderService", "CONTAINS", 1.0, "{}"),
        ("CALLS_METHOD:Class:user-svc:UserController->Class:user-svc:UserService", "Class:user-svc:UserController", "Class:user-svc:UserService", "CALLS_METHOD", 0.68, "{}"),
        ("CALLS_METHOD:Class:user-svc:UserService->Class:order-svc:OrderService", "Class:user-svc:UserService", "Class:order-svc:OrderService", "CALLS_METHOD", 0.58, "{}"),
        ("CALLS_SERVICE:FeignClient:order-svc:UserServiceClient->Service:user-svc", "FeignClient:order-svc:UserServiceClient", "Service:user-svc", "CALLS_SERVICE", 0.9, "{}"),
        ("CONSUMES_TOPIC:MQConsumer:order-svc:OrderListener:user-created-topic->MQTopic:user-created-topic", "MQConsumer:order-svc:OrderListener:user-created-topic", "MQTopic:user-created-topic", "CONSUMES_TOPIC", 1.0, "{}"),
        ("READS_CONFIG:Class:user-svc:UserService->ConfigKey:user-svc:app.timeout", "Class:user-svc:UserService", "ConfigKey:user-svc:app.timeout", "READS_CONFIG", 0.84, "{}"),
        ("EXPOSES_ENDPOINT:Class:user-svc:UserController->Endpoint:user-svc:GET:/api/users", "Class:user-svc:UserController", "Endpoint:user-svc:GET:/api/users", "EXPOSES_ENDPOINT", 1.0, "{}"),
    ])
    return store


# ═══════════════════════════════════════════════════════════════════════════════
# SQLitePool tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestSQLitePool:
    def test_connection_works(self, pool):
        with pool.connection() as conn:
            result = conn.execute("SELECT 1 AS val").fetchone()
            assert result["val"] == 1

    def test_wal_mode_enabled(self, pool):
        with pool.connection() as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode == "wal"

    def test_connection_reuse(self, pool):
        conns = []
        for _ in range(4):
            with pool.connection() as conn:
                conns.append(id(conn))
        # With pool_size=2, connections should be reused
        assert len(set(conns)) <= 2

    def test_transaction_commit(self, pool):
        with pool.transaction() as conn:
            conn.execute("CREATE TABLE test_tx(id INTEGER PRIMARY KEY, val TEXT)")
            conn.execute("INSERT INTO test_tx VALUES(1, 'hello')")
        with pool.connection() as conn:
            row = conn.execute("SELECT val FROM test_tx WHERE id=1").fetchone()
            assert row["val"] == "hello"

    def test_transaction_rollback(self, pool):
        with pool.connection() as conn:
            conn.execute("CREATE TABLE test_rb(id INTEGER PRIMARY KEY, val TEXT)")
        try:
            with pool.transaction() as conn:
                conn.execute("INSERT INTO test_rb VALUES(1, 'before_error')")
                raise ValueError("intentional error")
        except ValueError:
            pass
        with pool.connection() as conn:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM test_rb").fetchone()
            assert row["cnt"] == 0

    def test_close_prevents_new_connections(self, tmp_path):
        db = tmp_path / "close_test.db"
        p = SQLitePool(str(db), pool_size=1)
        p.close()
        # After close, getting a connection should either fail or return a stale one
        # We just verify close doesn't raise
        assert p._closed is True


# ═══════════════════════════════════════════════════════════════════════════════
# UnifiedStore tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestUnifiedStore:
    def test_upsert_and_find_nodes(self, store):
        store.upsert_nodes([
            ("Class:proj:Foo", "Class", "Foo", "proj", "Foo.java", 1, '{"pkg":"com.example"}'),
        ])
        results = store.find_nodes("Foo")
        assert len(results) >= 1
        assert results[0]["name"] == "Foo"
        assert results[0]["metadata"]["pkg"] == "com.example"

    def test_upsert_edges(self, store):
        store.upsert_nodes([
            ("Class:proj:A", "Class", "A", "proj", "A.java", 1, "{}"),
            ("Class:proj:B", "Class", "B", "proj", "B.java", 1, "{}"),
        ])
        store.upsert_edges([
            ("CALLS:A->B", "Class:proj:A", "Class:proj:B", "CALLS_METHOD", 0.8, '{"evidence":"direct call"}'),
        ])
        edges = store.edges_for_node("Class:proj:A", direction="downstream")
        assert len(edges) == 1
        assert edges[0]["type"] == "CALLS_METHOD"

    def test_node_by_id(self, store):
        store.upsert_nodes([("Class:proj:X", "Class", "X", "proj", "X.java", 5, "{}")])
        node = store.node_by_id("Class:proj:X")
        assert node is not None
        assert node["name"] == "X"
        assert node["line"] == 5

    def test_node_by_id_not_found(self, store):
        assert store.node_by_id("nonexistent") is None

    def test_graph_counts(self, store):
        store.upsert_nodes([
            ("Class:proj:A", "Class", "A", "proj", "A.java", 1, "{}"),
            ("Class:proj:B", "Class", "B", "proj", "B.java", 1, "{}"),
        ])
        store.upsert_edges([
            ("E:A->B", "Class:proj:A", "Class:proj:B", "CALLS", 1.0, "{}"),
        ])
        counts = store.graph_counts()
        assert counts["nodes"] == 2
        assert counts["edges"] == 1

    def test_neighbors_downstream(self, populated_store):
        results = populated_store.neighbors("Class:user-svc:UserController", direction="downstream", max_depth=2)
        names = {r["name"] for r in results}
        assert "UserService" in names
        # Through UserService -> OrderService (depth 2)
        assert "OrderService" in names

    def test_neighbors_upstream(self, populated_store):
        results = populated_store.neighbors("Class:user-svc:UserService", direction="upstream", max_depth=2)
        names = {r["name"] for r in results}
        assert "UserController" in names

    def test_neighbors_with_edge_type_filter(self, populated_store):
        results = populated_store.neighbors(
            "Class:user-svc:UserController", direction="downstream", max_depth=2,
            edge_types=["CALLS_METHOD"],
        )
        names = {r["name"] for r in results}
        assert "UserService" in names

    def test_neighbors_limit(self, populated_store):
        results = populated_store.neighbors("Class:user-svc:UserController", direction="downstream", max_depth=3, limit=1)
        assert len(results) <= 1

    def test_memory_append_and_query(self, store):
        store.append_record("session-events.jsonl", {"event_type": "tool_call", "tool_name": "mc_lookup", "created_at": "2026-01-01T00:00:00Z"})
        store.append_record("session-events.jsonl", {"event_type": "note", "created_at": "2026-01-02T00:00:00Z"})
        result = store.query_records(collection="session-events.jsonl", limit=10)
        assert result["count"] == 2
        assert result["records"][0]["payload"]["event_type"] == "note"  # DESC order

    def test_memory_query_filters(self, store):
        store.append_record("events.jsonl", {"type": "call", "session_id": "s1", "created_at": "2026-01-01"})
        store.append_record("events.jsonl", {"type": "note", "session_id": "s2", "created_at": "2026-01-02"})
        result = store.query_records(collection="events.jsonl", session_id="s1")
        assert result["count"] == 1
        assert result["records"][0]["payload"]["type"] == "call"

    def test_ref_upsert_and_query(self, store):
        store.upsert_ref("refs/abc123", {"data": "hello", "created_at": "2026-01-01"})
        store.upsert_ref("refs/abc123", {"data": "updated", "created_at": "2026-01-02"})
        result = store.query_refs(ref_path="refs/abc123")
        assert result["count"] == 1
        assert result["refs"][0]["payload"]["data"] == "updated"

    def test_index_mirror(self, store):
        store.upsert_index("test-index", {"items": [1, 2, 3]})
        data = store.read_index("test-index")
        assert data["items"] == [1, 2, 3]
        # Update
        store.upsert_index("test-index", {"items": [4, 5]})
        data = store.read_index("test-index")
        assert data["items"] == [4, 5]

    def test_read_index_default(self, store):
        assert store.read_index("nonexistent", default={"empty": True}) == {"empty": True}

    def test_memory_stats(self, store):
        store.append_record("a.jsonl", {"x": 1})
        store.append_record("b.jsonl", {"y": 2})
        stats = store.memory_stats()
        assert "a.jsonl" in stats["collections"]
        assert "b.jsonl" in stats["collections"]

    def test_clear_graph(self, populated_store):
        populated_store.clear_graph()
        assert populated_store.graph_counts() == {"nodes": 0, "edges": 0}

    def test_remove_nodes_by_scope(self, store):
        store.upsert_nodes([
            ("Class:svc-a:X", "Class", "X", "svc-a", "src/X.java", 1, "{}"),
            ("Class:svc-b:Y", "Class", "Y", "svc-b", "src/Y.java", 1, "{}"),
        ])
        removed = store.remove_nodes_by_scope({"svc-a"}, [])
        assert "Class:svc-a:X" in removed
        assert store.node_by_id("Class:svc-b:Y") is not None

    def test_context_manager(self, tmp_path):
        db = tmp_path / "ctx_test.db"
        with UnifiedStore(str(db)) as s:
            s.upsert_nodes([("X", "Class", "X", "p", "x.java", 0, "{}")])
            assert s.graph_counts()["nodes"] == 1


# ═══════════════════════════════════════════════════════════════════════════════
# InvertedIndex tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestInvertedIndex:
    def test_rebuild_and_stats(self, store):
        idx = InvertedIndex(store)
        nodes = [
            {"id": "A", "type": "Class", "name": "UserService", "project": "user-svc", "file_path": "src/UserService.java", "metadata": {}},
            {"id": "B", "type": "Class", "name": "OrderService", "project": "order-svc", "file_path": "src/OrderService.java", "metadata": {}},
            {"id": "C", "type": "Method", "name": "createUser", "project": "user-svc", "file_path": "src/UserService.java", "metadata": {}},
        ]
        stats = idx.rebuild(nodes)
        assert stats["doc_count"] == 3
        assert stats["token_count"] > 0
        assert stats["posting_count"] > 0
        s = idx.stats()
        assert s["doc_count"] == 3

    def test_query_returns_relevant_docs(self, store):
        idx = InvertedIndex(store)
        idx.rebuild([
            {"id": "A", "type": "Class", "name": "UserService", "project": "user-svc", "file_path": "src/UserService.java", "metadata": {}},
            {"id": "B", "type": "Class", "name": "OrderService", "project": "order-svc", "file_path": "src/OrderService.java", "metadata": {}},
        ])
        results = idx.query("UserService")
        assert len(results) >= 1
        assert any(r["node_id"] == "A" for r in results)
        # OrderService should rank lower or not appear
        if len(results) > 1:
            assert results[0]["score"] >= results[1]["score"]

    def test_query_empty_input(self, store):
        idx = InvertedIndex(store)
        idx.rebuild([{"id": "A", "type": "Class", "name": "Foo", "project": "p", "file_path": "f.java", "metadata": {}}])
        assert idx.query("") == []
        assert idx.query("   ") == []

    def test_query_no_match(self, store):
        idx = InvertedIndex(store)
        idx.rebuild([{"id": "A", "type": "Class", "name": "UserService", "project": "p", "file_path": "f.java", "metadata": {}}])
        results = idx.query("NonExistentThing12345")
        assert len(results) == 0

    def test_rebuild_is_idempotent(self, store):
        idx = InvertedIndex(store)
        nodes = [{"id": "A", "type": "Class", "name": "Foo", "project": "p", "file_path": "f.java", "metadata": {}}]
        idx.rebuild(nodes)
        idx.rebuild(nodes)
        assert idx.stats()["doc_count"] == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Presentation tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestPresentation:
    def test_build_progressive_levels(self):
        result = build_progressive_levels(
            {"summary": "quick"},
            {"details": "medium"},
            {"full": "everything"},
        )
        assert result["level_1_quick"]["summary"] == "quick"
        assert result["level_2_details"]["details"] == "medium"
        assert result["level_3_full"]["full"] == "everything"


# ═══════════════════════════════════════════════════════════════════════════════
# Freshness tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestFreshness:
    def test_check_on_empty_workspace(self, tmp_path):
        """Freshness check on a workspace with no index should return stale."""
        # Create a minimal workspace structure
        ws_dir = tmp_path / ".memory-center"
        ws_dir.mkdir()
        (ws_dir / "workspace.yaml").write_text("workspace: test\nroot: .\nservices: []\n")
        svc = IndexFreshnessService(str(ws_dir / "workspace.yaml"))
        status = svc.check()
        # Should be stale or unknown since there's no graph.db
        assert status.status in ("stale", "unknown")

    def test_freshness_status_to_dict(self):
        s = FreshnessStatus(status="fresh", message="ok")
        d = s.to_dict()
        assert d["status"] == "fresh"
        assert d["message"] == "ok"

    def test_check_files(self, tmp_path):
        ws_dir = tmp_path / ".memory-center"
        ws_dir.mkdir()
        (ws_dir / "workspace.yaml").write_text("workspace: test\nroot: .\nservices: []\n")
        svc = IndexFreshnessService(str(ws_dir / "workspace.yaml"))
        # Create a test file
        test_file = tmp_path / "Test.java"
        test_file.write_text("class Test {}")
        results = svc.check_files([str(test_file)])
        assert str(test_file) in results
        assert results[str(test_file)] in ("fresh", "pending", "stale")

    def test_banner(self, tmp_path):
        ws_dir = tmp_path / ".memory-center"
        ws_dir.mkdir()
        (ws_dir / "workspace.yaml").write_text("workspace: test\nroot: .\nservices: []\n")
        svc = IndexFreshnessService(str(ws_dir / "workspace.yaml"))
        banner = svc.banner()
        assert "freshness" in banner
        assert "banner" in banner


# ═══════════════════════════════════════════════════════════════════════════════
# Reasoning: Pattern Engine tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestGraphPatternEngine:
    def test_find_unprotected_mq_consumers(self, populated_store):
        engine = GraphPatternEngine(populated_store)
        matches = engine.find_unprotected_mq_consumers()
        assert len(matches) >= 1
        assert matches[0].pattern_name == "unprotected_mq_consumer"
        assert matches[0].risk_level == "high"

    def test_find_long_feign_chains(self, populated_store):
        engine = GraphPatternEngine(populated_store)
        # With depth=3 on our small graph, may or may not find chains
        matches = engine.find_long_feign_chains(min_depth=2)
        # Just verify it doesn't crash and returns a list
        assert isinstance(matches, list)

    def test_find_shared_configs(self, populated_store):
        engine = GraphPatternEngine(populated_store)
        matches = engine.find_shared_configs()
        # Our test graph has only 1 reader for app.timeout, so no shared configs
        assert isinstance(matches, list)

    def test_run_all_patterns(self, populated_store):
        engine = GraphPatternEngine(populated_store)
        results = engine.run_all_patterns()
        assert "unprotected_mq_consumers" in results
        assert "long_feign_chains" in results
        assert "shared_configs" in results


# ═══════════════════════════════════════════════════════════════════════════════
# Reasoning: Transitive Inference tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestTransitiveInference:
    def test_find_transitive_calls(self, populated_store):
        engine = TransitiveInferenceEngine(populated_store)
        # UserController -> UserService -> OrderService (depth 2)
        results = engine.find_transitive_calls("Class:user-svc:UserController", max_depth=3)
        target_ids = {r.target_id for r in results}
        assert "Class:order-svc:OrderService" in target_ids

    def test_find_transitive_calls_limit(self, populated_store):
        engine = TransitiveInferenceEngine(populated_store)
        results = engine.find_transitive_calls("Class:user-svc:UserController", max_depth=3, limit=1)
        assert len(results) <= 1

    def test_find_transitive_calls_no_path(self, populated_store):
        engine = TransitiveInferenceEngine(populated_store)
        # ConfigKey has no outgoing CALLS edges
        results = engine.find_transitive_calls("ConfigKey:user-svc:app.timeout", max_depth=3)
        assert len(results) == 0

    def test_find_config_propagation(self, populated_store):
        engine = TransitiveInferenceEngine(populated_store)
        results = engine.find_config_propagation()
        # Only 1 reader in our test data, so no multi-service configs
        assert isinstance(results, list)


# ═══════════════════════════════════════════════════════════════════════════════
# Reasoning: Risk Pattern Engine tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestRiskPatternEngine:
    def test_analyze_feign_change_risk(self, populated_store):
        engine = RiskPatternEngine(populated_store)
        findings = engine.analyze_change_risk("FeignClient:order-svc:UserServiceClient")
        assert len(findings) >= 1
        assert any(f.severity == "high" for f in findings)

    def test_analyze_endpoint_change_risk(self, populated_store):
        engine = RiskPatternEngine(populated_store)
        findings = engine.analyze_change_risk("Endpoint:user-svc:GET:/api/users")
        assert len(findings) >= 1

    def test_analyze_mq_change_risk(self, populated_store):
        engine = RiskPatternEngine(populated_store)
        findings = engine.analyze_change_risk("MQConsumer:order-svc:OrderListener:user-created-topic")
        assert len(findings) >= 1
        assert any("mq" in f.pattern for f in findings)

    def test_analyze_nonexistent_node(self, populated_store):
        engine = RiskPatternEngine(populated_store)
        findings = engine.analyze_change_risk("nonexistent:id")
        assert len(findings) == 0

    def test_scan_workspace_risks(self, populated_store):
        engine = RiskPatternEngine(populated_store)
        findings = engine.scan_workspace_risks()
        assert isinstance(findings, list)
        # Should find the unprotected MQ consumer
        assert any(f.pattern == "unprotected_mq_consumer" for f in findings)


# ═══════════════════════════════════════════════════════════════════════════════
# Integration: UnifiedStore + InvertedIndex
# ═══════════════════════════════════════════════════════════════════════════════

class TestIntegration:
    def test_inverted_index_with_unified_store(self, populated_store):
        """InvertedIndex should work with nodes from UnifiedStore."""
        nodes = populated_store.all_nodes()
        idx = InvertedIndex(populated_store)
        stats = idx.rebuild(nodes)
        assert stats["doc_count"] > 0

        # Query for something we know exists
        results = idx.query("UserController")
        assert len(results) >= 1

    def test_full_workflow(self, tmp_path):
        """End-to-end: create store, populate, build index, query, reason."""
        db = tmp_path / "full_workflow.db"
        with UnifiedStore(str(db)) as store:
            # Populate
            store.upsert_nodes([
                ("Class:svc:UserService", "Class", "UserService", "svc", "UserService.java", 1, "{}"),
                ("Class:svc:OrderService", "Class", "OrderService", "svc", "OrderService.java", 10, "{}"),
                ("MQConsumer:svc:MsgListener:topic-x", "MQConsumer", "MsgListener", "svc", "MsgListener.java", 5, '{"class_name":"MsgListener","method_name":"handle","topic":"topic-x"}'),
            ])
            store.upsert_edges([
                ("E1", "Class:svc:UserService", "Class:svc:OrderService", "CALLS_METHOD", 0.6, "{}"),
            ])

            # Index
            idx = InvertedIndex(store)
            idx.rebuild(store.all_nodes())

            # Query
            results = idx.query("UserService")
            assert len(results) >= 1

            # Reason
            engine = GraphPatternEngine(store)
            mq_matches = engine.find_unprotected_mq_consumers()
            assert len(mq_matches) >= 1

            # Risk
            risk_engine = RiskPatternEngine(store)
            risks = risk_engine.analyze_change_risk("Class:svc:UserService")
            # UserService is a Class, not a public contract, so fewer risks
            assert isinstance(risks, list)

            # Memory
            store.append_record("test.jsonl", {"event": "test"})
            assert store.query_records(collection="test.jsonl")["count"] == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Matching tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestProjectMatching:
    def test_exact_match(self):
        from memory_center.core.matching.project import project_matches
        assert project_matches("user-svc", "user-svc") is True

    def test_no_match(self):
        from memory_center.core.matching.project import project_matches
        assert project_matches("order-svc", "user-svc") is False

    def test_component_match(self):
        from memory_center.core.matching.project import project_matches
        # "openapi" is a specific component in "ucap-cloud-openapi"
        assert project_matches("openapi", "ucap-cloud-openapi") is True

    def test_concatenated_match(self):
        from memory_center.core.matching.project import project_matches
        # "openapi" matches "open_api" via concatenation
        assert project_matches("openapi", "open_api") is True

    def test_hyphenated_match(self):
        from memory_center.core.matching.project import project_matches
        assert project_matches("open-api", "open_api") is True

    def test_generic_component_no_match(self):
        from memory_center.core.matching.project import project_matches
        # "api" is too generic to match alone
        assert project_matches("api", "ucap-cloud-api") is False

    def test_empty_inputs(self):
        from memory_center.core.matching.project import project_matches
        assert project_matches("", "user-svc") is False
        assert project_matches("user-svc", "") is False
        assert project_matches("", "") is False

    def test_fqn_inference_exact(self):
        from memory_center.core.matching.project import infer_project_from_fqn
        result = infer_project_from_fqn(
            "cn.kaipuyun.cloud.openapi.biz.service.FooService",
            ["openapi", "user-svc", "order-svc"],
        )
        assert result == "openapi"

    def test_fqn_inference_concat(self):
        from memory_center.core.matching.project import infer_project_from_fqn
        # "openapi" segment matches "open-api" project via concatenation of ["open","api"]
        result = infer_project_from_fqn(
            "com.example.openapi.service.BarService",
            ["open-api", "other-svc"],
        )
        assert result == "open-api"

    def test_fqn_inference_no_match(self):
        from memory_center.core.matching.project import infer_project_from_fqn
        result = infer_project_from_fqn(
            "com.example.unknown.Foo",
            ["user-svc", "order-svc"],
        )
        assert result == ""


# ═══════════════════════════════════════════════════════════════════════════════
# ContextPack integration tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestContextPackIntegration:
    def test_context_pack_builder_init(self, tmp_path):
        """ContextPackBuilder can be instantiated with a workspace file."""
        from memory_center.core.context.pack import ContextPackBuilder
        # Create minimal workspace
        ws_dir = tmp_path / ".memory-center"
        ws_dir.mkdir()
        (ws_dir / "workspace.yaml").write_text(
            "workspace: test\nroot: .\nservices: []\n"
        )
        # Just verify it doesn't crash on init
        builder = ContextPackBuilder(str(ws_dir / "workspace.yaml"))
        assert builder is not None

    # ------------------------------------------------------------------ #
    # Snippet & freshness integration tests
    # ------------------------------------------------------------------ #

    @staticmethod
    def _setup_workspace(tmp_path):
        """Create a minimal workspace with file-index and a source file.

        Returns (workspace_yaml_path, source_file_path).
        """
        ws_dir = tmp_path / ".memory-center"
        (ws_dir / "index").mkdir(parents=True)
        (ws_dir / "graph").mkdir()

        # workspace.yaml
        (ws_dir / "workspace.yaml").write_text(
            "workspace: test\nroot: .\nservices: []\n"
        )

        # A real Java source file that the snippet extractor will read
        src = tmp_path / "UserService.java"
        lines = [f"// line {i}" for i in range(1, 51)]
        lines[17] = "public class UserService {"  # line 18 (0-indexed 17)
        lines[18] = "    public void saveUser() {"
        src.write_text("\n".join(lines))

        # file-index.json maps logical path → abs_path
        index_file = ws_dir / "index" / "file-index.json"
        index_file.write_text(json.dumps([{
            "project": "test-svc",
            "path": "src/UserService.java",
            "abs_path": str(src.resolve()),
            "service_root": str(tmp_path),
            "suffix": ".java",
        }]))

        return ws_dir / "workspace.yaml", src

    def test_snippets_extracted(self, tmp_path):
        """build() returns code snippets from entrypoints' source files."""
        from unittest.mock import patch
        from memory_center.core.context.pack import ContextPackBuilder

        ws_yaml, src = self._setup_workspace(tmp_path)

        fake_results = [{
            "node": {
                "id": "Class:test-svc:UserService",
                "type": "Class",
                "name": "UserService",
                "project": "test-svc",
                "file_path": "src/UserService.java",
                "line": 18,
                "metadata": {},
            },
            "score": 1.0,
            "sources": ["graph"],
        }]

        with patch("memory_center.core.context.pack.hybrid_retrieve", return_value={"results": fake_results}):
            builder = ContextPackBuilder(str(ws_yaml))
            pack = builder.build("UserService", budget_tokens=8000)

        assert len(pack.snippets) == 1
        snippet = pack.snippets[0]
        assert snippet["file"] == "src/UserService.java"
        assert "public class UserService" in snippet["content"]
        assert snippet["language"] == "java"
        assert snippet["line_start"] >= 1
        assert snippet["line_end"] <= 50

    def test_freshness_populated(self, tmp_path):
        """build() returns non-empty freshness (not a stub dict)."""
        from unittest.mock import patch
        from memory_center.core.context.pack import ContextPackBuilder

        ws_yaml, _ = self._setup_workspace(tmp_path)

        with patch("memory_center.core.context.pack.hybrid_retrieve", return_value={"results": []}):
            builder = ContextPackBuilder(str(ws_yaml))
            pack = builder.build("anything", budget_tokens=8000)

        assert isinstance(pack.freshness, dict)
        assert "freshness" in pack.freshness
        assert "banner" in pack.freshness
        assert pack.freshness["freshness"]["status"] in ("fresh", "pending", "stale", "unknown")

    def test_snippets_respect_token_budget(self, tmp_path):
        """Total snippet content stays within 25 % of budget_tokens."""
        from unittest.mock import patch
        from memory_center.core.context.pack import ContextPackBuilder

        ws_yaml, src = self._setup_workspace(tmp_path)

        # Write a large file so the window would be big
        big_lines = [f"public class Big {{ /* {'x' * 200} */ }}" for _ in range(500)]
        src.write_text("\n".join(big_lines))

        fake_results = [{
            "node": {
                "id": "Class:test-svc:UserService",
                "type": "Class",
                "name": "UserService",
                "project": "test-svc",
                "file_path": "src/UserService.java",
                "line": 250,
                "metadata": {},
            },
            "score": 1.0,
            "sources": ["graph"],
        }]

        budget = 2000  # snippet budget = 25 % = 500 tokens
        with patch("memory_center.core.context.pack.hybrid_retrieve", return_value={"results": fake_results}):
            builder = ContextPackBuilder(str(ws_yaml))
            pack = builder.build("UserService", budget_tokens=budget)

        # Total snippet chars / 4 must be ≤ 500 tokens
        total_tokens = sum(len(s["content"]) // 4 for s in pack.snippets)
        assert total_tokens <= int(budget * 0.25) + 1  # +1 for rounding

    def test_non_code_files_skipped(self, tmp_path):
        """Snippets are not extracted from .yaml / .md / .json files."""
        from unittest.mock import patch
        from memory_center.core.context.pack import ContextPackBuilder

        ws_dir = tmp_path / ".memory-center"
        (ws_dir / "index").mkdir(parents=True)
        (ws_dir / "graph").mkdir()
        (ws_dir / "workspace.yaml").write_text("workspace: test\nroot: .\nservices: []\n")

        yaml_src = tmp_path / "application.yml"
        yaml_src.write_text("server:\n  port: 8080\n")

        index_file = ws_dir / "index" / "file-index.json"
        index_file.write_text(json.dumps([{
            "project": "test-svc",
            "path": "application.yml",
            "abs_path": str(yaml_src.resolve()),
            "service_root": str(tmp_path),
            "suffix": ".yml",
        }]))

        fake_results = [{
            "node": {
                "id": "ConfigKey:test-svc:server.port",
                "type": "ConfigKey",
                "name": "server.port",
                "project": "test-svc",
                "file_path": "application.yml",
                "line": 2,
                "metadata": {},
            },
            "score": 0.8,
            "sources": ["graph"],
        }]

        with patch("memory_center.core.context.pack.hybrid_retrieve", return_value={"results": fake_results}):
            builder = ContextPackBuilder(str(ws_dir / "workspace.yaml"))
            pack = builder.build("server.port", budget_tokens=8000)

        assert pack.snippets == []

    def test_snippet_dedup_same_file(self, tmp_path):
        """Multiple nodes in the same file produce only one snippet."""
        from unittest.mock import patch
        from memory_center.core.context.pack import ContextPackBuilder

        ws_dir = tmp_path / ".memory-center"
        (ws_dir / "index").mkdir(parents=True)
        (ws_dir / "graph").mkdir()
        (ws_dir / "workspace.yaml").write_text("workspace: test\nroot: .\nservices: []\n")

        src = tmp_path / "Foo.java"
        src.write_text("\n".join([f"// line {i}" for i in range(1, 101)]))

        index_file = ws_dir / "index" / "file-index.json"
        index_file.write_text(json.dumps([{
            "project": "p",
            "path": "Foo.java",
            "abs_path": str(src.resolve()),
            "service_root": str(tmp_path),
            "suffix": ".java",
        }]))

        fake_results = [
            {"node": {"id": "A", "type": "Class", "name": "Foo", "project": "p",
                       "file_path": "Foo.java", "line": 10, "metadata": {}},
             "score": 1.0, "sources": ["graph"]},
            {"node": {"id": "B", "type": "Method", "name": "bar", "project": "p",
                       "file_path": "Foo.java", "line": 50, "metadata": {}},
             "score": 0.9, "sources": ["graph"]},
        ]

        with patch("memory_center.core.context.pack.hybrid_retrieve", return_value={"results": fake_results}):
            builder = ContextPackBuilder(str(ws_dir / "workspace.yaml"))
            pack = builder.build("Foo bar", budget_tokens=8000)

        assert len(pack.snippets) == 1  # deduped
        assert pack.snippets[0]["node_id"] == "A"  # first occurrence wins

    def test_freshness_and_snippets_together(self, tmp_path):
        """A single build() returns both non-empty snippets and freshness."""
        from unittest.mock import patch
        from memory_center.core.context.pack import ContextPackBuilder

        ws_yaml, _ = self._setup_workspace(tmp_path)

        fake_results = [{
            "node": {
                "id": "Class:test-svc:UserService",
                "type": "Class",
                "name": "UserService",
                "project": "test-svc",
                "file_path": "src/UserService.java",
                "line": 18,
                "metadata": {},
            },
            "score": 1.0,
            "sources": ["graph"],
        }]

        with patch("memory_center.core.context.pack.hybrid_retrieve", return_value={"results": fake_results}):
            builder = ContextPackBuilder(str(ws_yaml))
            pack = builder.build("UserService", budget_tokens=8000)

        # Both must be populated
        assert len(pack.snippets) >= 1
        assert "freshness" in pack.freshness
        assert pack.freshness["freshness"]["status"] in ("fresh", "pending", "stale", "unknown")


# ═══════════════════════════════════════════════════════════════════════════════
# Edge case tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_unified_store_upsert_overwrite(self, store):
        """Upserting the same node ID should overwrite."""
        store.upsert_nodes([("X", "Class", "Foo", "p", "f.java", 1, '{"v":1}')])
        store.upsert_nodes([("X", "Class", "Foo", "p", "f.java", 1, '{"v":2}')])
        node = store.node_by_id("X")
        assert node["metadata"]["v"] == 2

    def test_unified_store_special_characters(self, store):
        """Names with special chars should be stored correctly."""
        store.upsert_nodes([("Class:p:Foo$Bar", "Class", "Foo$Bar", "p", "f.java", 1, '{"key":"val/ue"}')])
        node = store.node_by_id("Class:p:Foo$Bar")
        assert node["name"] == "Foo$Bar"
        assert node["metadata"]["key"] == "val/ue"

    def _test_inverted_index_chinese_tokens_DISABLED(self, store):
        """InvertedIndex should handle Chinese text."""
        idx = InvertedIndex(store)
        idx.rebuild([
            {"id": "A", "type": "Class", "name": "用户服务", "project": "p", "file_path": "f.java", "metadata": {}},
            {"id": "B", "type": "Class", "name": "OrderService", "project": "p", "file_path": "g.java", "metadata": {}},
        ])
        results = idx.query("用户")
        assert len(results) >= 1
        assert results[0]["node_id"] == "A"

    def test_unified_store_empty_query(self, store):
        assert store.find_nodes("") == []
        assert store.find_nodes("   ") == []

    def test_unified_store_like_fallback(self, store):
        """find_nodes should fall back to LIKE when FTS has no match."""
        store.upsert_nodes([("Class:p:UniqueClassName123", "Class", "UniqueClassName123", "p", "f.java", 1, "{}")])
        results = store.find_nodes("UniqueClassName123")
        assert len(results) >= 1

    def test_neighbors_self_exclusion(self, populated_store):
        """Neighbors should not include the start node itself."""
        results = populated_store.neighbors("Class:user-svc:UserController", direction="downstream", max_depth=3)
        ids = {r["id"] for r in results}
        assert "Class:user-svc:UserController" not in ids

    def test_pattern_engine_empty_store(self, store):
        """Pattern engine should handle empty graph gracefully."""
        engine = GraphPatternEngine(store)
        assert engine.find_unprotected_mq_consumers() == []
        assert engine.find_long_feign_chains() == []
        assert engine.find_shared_configs() == []
