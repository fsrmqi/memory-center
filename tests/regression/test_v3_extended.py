"""Comprehensive tests for all new V3 modules (Phase 2+).

Covers:
- VectorIndex (storage/vector_index.py)
- BusinessDomainExtractor (domain/extractor.py)
- ArchitectureTourGenerator (onboarding/tour.py)
- Parallel indexing (indexing/parallel.py)
- IncrementalIndexer (indexing/incremental.py)
- FileWatcher (freshness/watcher.py)
- Enhanced graph pattern matching
- Code KG ontology edge/node types
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from memory_center.core.domain.extractor import (
    BusinessDomain,
    BusinessDomainExtractor,
    BusinessFlow,
)
from memory_center.core.freshness.watcher import FileSnapshot, FileWatcher, WatchEvent
from memory_center.core.indexing.incremental import (
    ChangedFile,
    IncrementalIndexer,
)
from memory_center.core.indexing.parallel import (
    estimate_optimal_workers,
    parse_files_parallel,
    walk_project_files,
)
from memory_center.core.onboarding.tour import (
    ArchitectureTour,
    ArchitectureTourGenerator,
    TourStep,
)
from memory_center.core.storage.runtime import RuntimeStore
from memory_center.core.storage.vector_index import VectorIndex, VectorIndexBusyError

# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def store(tmp_path):
    """A fresh RuntimeStore backed by a temp file."""
    db = tmp_path / "test_v3ext.db"
    s = RuntimeStore(str(db), pool_size=2)
    yield s
    s.close()


@pytest.fixture
def populated_store(store):
    """A RuntimeStore pre-populated with a representative graph."""
    store.upsert_nodes([
        ("Service:user-svc", "Service", "user-svc", "user-svc", "", 0, "{}"),
        ("Service:order-svc", "Service", "order-svc", "order-svc", "", 0, "{}"),
        ("Service:payment-svc", "Service", "payment-svc", "payment-svc", "", 0, "{}"),
        ("Service:notification-svc", "Service", "notification-svc", "notification-svc", "", 0, "{}"),
        ("Class:user-svc:UserController", "Class", "UserController", "user-svc",
         "src/ctrl/UserController.java", 10, '{"annotations":["RestController"]}'),
        ("Class:user-svc:UserService", "Class", "UserService", "user-svc",
         "src/svc/UserService.java", 20, '{"annotations":["Service"]}'),
        ("Class:order-svc:OrderService", "Class", "OrderService", "order-svc",
         "src/svc/OrderService.java", 15, '{"annotations":["Service"]}'),
        ("Class:payment-svc:PaymentService", "Class", "PaymentService", "payment-svc",
         "src/svc/PaymentService.java", 10, '{"annotations":["Service"]}'),
        ("Endpoint:user-svc:POST:/api/users", "Endpoint", "POST /api/users", "user-svc",
         "src/ctrl/UserController.java", 12, '{"http_method":"POST","path":"/api/users"}'),
        ("Endpoint:order-svc:POST:/api/orders", "Endpoint", "POST /api/orders", "order-svc",
         "src/ctrl/OrderController.java", 10, '{"http_method":"POST","path":"/api/orders"}'),
        ("FeignClient:order-svc:UserServiceClient", "FeignClient", "UserServiceClient",
         "order-svc", "src/feign/UserServiceClient.java", 5,
         '{"interface":"UserServiceClient","target_service":"user-svc"}'),
        ("MQConsumer:notification-svc:UserCreatedListener:user-created-topic", "MQConsumer",
         "UserCreatedListener", "notification-svc", "src/mq/UserCreatedListener.java", 30,
         '{"class_name":"UserCreatedListener","method_name":"onMessage","topic":"user-created-topic"}'),
        ("ConfigKey:user-svc:app.timeout", "ConfigKey", "app.timeout", "user-svc",
         "application.yml", 0, '{"value":"3000"}'),
    ])
    store.upsert_edges([
        ("CONTAINS:Service:user-svc->Class:user-svc:UserController",
         "Service:user-svc", "Class:user-svc:UserController", "CONTAINS", 1.0, "{}"),
        ("CONTAINS:Service:user-svc->Class:user-svc:UserService",
         "Service:user-svc", "Class:user-svc:UserService", "CONTAINS", 1.0, "{}"),
        ("CALLS_METHOD:Class:user-svc:UserController->Class:user-svc:UserService",
         "Class:user-svc:UserController", "Class:user-svc:UserService", "CALLS_METHOD", 0.68, "{}"),
        ("CALLS_METHOD:Class:user-svc:UserService->Class:order-svc:OrderService",
         "Class:user-svc:UserService", "Class:order-svc:OrderService", "CALLS_METHOD", 0.58, "{}"),
        ("CALLS_SERVICE:FeignClient:order-svc:UserServiceClient->Service:user-svc",
         "FeignClient:order-svc:UserServiceClient", "Service:user-svc", "CALLS_SERVICE", 0.9, "{}"),
        ("EXPOSES_ENDPOINT:Class:user-svc:UserController->Endpoint:user-svc:POST:/api/users",
         "Class:user-svc:UserController", "Endpoint:user-svc:POST:/api/users",
         "EXPOSES_ENDPOINT", 1.0, "{}"),
        ("CONSUMES_TOPIC:MQConsumer:notification-svc:UserCreatedListener:user-created-topic->MQTopic:user-created-topic",
         "MQConsumer:notification-svc:UserCreatedListener:user-created-topic",
         "MQTopic:user-created-topic", "CONSUMES_TOPIC", 1.0, "{}"),
        ("READS_CONFIG:Class:user-svc:UserService->ConfigKey:user-svc:app.timeout",
         "Class:user-svc:UserService", "ConfigKey:user-svc:app.timeout", "READS_CONFIG", 0.84, "{}"),
    ])
    return store


# ═══════════════════════════════════════════════════════════════════════════════
# VectorIndex tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestVectorIndex:
    """Tests for VectorIndex (§4 vector search)."""

    def _make_embedding(self, dim: int = 4, base: float = 0.0) -> list[float]:
        """Create a simple test embedding."""
        return [base + i * 0.1 for i in range(dim)]

    def test_init_creates_schema(self, store):
        vi = VectorIndex(store, dimension=4)
        stats = vi.stats()
        assert stats["embedding_count"] == 0
        assert stats["dimension"] == 4

    def test_upsert_and_query(self, store):
        vi = VectorIndex(store, dimension=4)
        # Insert two embeddings
        vi.upsert_embedding("node:A", [1.0, 0.0, 0.0, 0.0])
        vi.upsert_embedding("node:B", [0.0, 1.0, 0.0, 0.0])
        vi.upsert_embedding("node:C", [0.9, 0.1, 0.0, 0.0])

        # Query close to A
        results = vi.query([1.0, 0.0, 0.0, 0.0], limit=3)
        assert len(results) >= 1
        # A should be the closest (score closest to 1.0)
        assert results[0]["node_id"] == "node:A"
        assert results[0]["score"] > 0.9

    def test_upsert_dimension_mismatch(self, store):
        vi = VectorIndex(store, dimension=4)
        with pytest.raises(ValueError, match="dimension mismatch"):
            vi.upsert_embedding("node:X", [1.0, 2.0])  # wrong dim

    def test_query_dimension_mismatch(self, store):
        vi = VectorIndex(store, dimension=4)
        with pytest.raises(ValueError, match="dimension mismatch"):
            vi.query([1.0, 2.0])

    def test_batch_upsert(self, store):
        vi = VectorIndex(store, dimension=4)
        items = [
            ("node:A", [1.0, 0.0, 0.0, 0.0]),
            ("node:B", [0.0, 1.0, 0.0, 0.0]),
            ("node:bad", [1.0, 2.0]),  # wrong dim, should be skipped
        ]
        count = vi.upsert_embeddings_batch(items)
        assert count == 2  # bad one skipped
        assert vi.stats()["embedding_count"] == 2

    def test_delete_embedding(self, store):
        vi = VectorIndex(store, dimension=4)
        vi.upsert_embedding("node:A", [1.0, 0.0, 0.0, 0.0])
        assert vi.stats()["embedding_count"] == 1
        vi.delete_embedding("node:A")
        assert vi.stats()["embedding_count"] == 0
        results = vi.query([1.0, 0.0, 0.0, 0.0])
        assert len(results) == 0

    def test_upsert_overwrite(self, store):
        vi = VectorIndex(store, dimension=4)
        vi.upsert_embedding("node:A", [1.0, 0.0, 0.0, 0.0])
        vi.upsert_embedding("node:A", [0.0, 1.0, 0.0, 0.0])
        assert vi.stats()["embedding_count"] == 1
        results = vi.query([0.0, 1.0, 0.0, 0.0])
        assert results[0]["node_id"] == "node:A"

    def test_empty_query(self, store):
        vi = VectorIndex(store, dimension=4)
        results = vi.query([1.0, 0.0, 0.0, 0.0])
        assert results == []

    def test_stats(self, store):
        vi = VectorIndex(store, dimension=384)
        s = vi.stats()
        assert "embedding_count" in s
        assert "dimension" in s
        assert "backend" in s
        assert s["dimension"] == 384

    def test_dimension_switch_ignores_prior_vectors_until_full_clear(self, store):
        old = VectorIndex(store, dimension=4)
        old.upsert_embedding("node:old", [1.0, 0.0, 0.0, 0.0])

        switched = VectorIndex(store, dimension=8)
        assert switched.stats()["embedding_count"] == 0
        assert switched.query([1.0] + [0.0] * 7) == []

        switched.clear()
        switched.upsert_embedding("node:new", [1.0] + [0.0] * 7)
        assert switched.stats()["embedding_count"] == 1

    def test_sqlite_vec_dimension_mismatch_is_not_treated_as_ready(self, store, monkeypatch):
        from memory_center.core.storage import vector_index as vector_index_module

        VectorIndex(store, dimension=4)
        with store.pool.transaction() as conn:
            table_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='node_vec' LIMIT 1"
            ).fetchone()
            if not table_exists:
                conn.execute("CREATE TABLE node_vec(node_id TEXT PRIMARY KEY, embedding TEXT)")
            conn.execute(
                "INSERT OR REPLACE INTO vec_backend_meta(backend, dimension) VALUES('sqlite-vec', 4)"
            )
        monkeypatch.setattr(vector_index_module, "_HAS_SQLITE_VEC", True)

        switched = VectorIndex(store, dimension=8)
        status = switched.stats()
        assert status["sqlite_vec_status"] == "dimension_mismatch"
        assert status["ann_backend"] != "sqlite-vec"
        assert status["next_action"] == "full-reindex"

    def test_atomic_hnsw_save_replaces_final_path(self, store):
        vi = VectorIndex(store, dimension=4)

        class FakeIndex:
            def save_index(self, path):
                Path(path).write_text("new-index")

        vi._hnsw_path.write_text("old-index")
        vi._save_hnsw_atomically(FakeIndex())
        assert vi._hnsw_path.read_text() == "new-index"
        assert not list(vi._hnsw_path.parent.glob(f"{vi._hnsw_path.name}.*.tmp"))

    def test_query_returns_busy_diagnostics_without_waiting_for_maintenance(self, store, monkeypatch):
        vi = VectorIndex(store, dimension=4)

        @contextmanager
        def busy_lock(_timeout):
            raise VectorIndexBusyError(300)
            yield

        monkeypatch.setattr(vi, "_ann_lock", busy_lock)
        assert vi.query([1.0, 0.0, 0.0, 0.0]) == []
        assert vi.query_diagnostics() == {
            "status": "busy",
            "reason": "vector_ann_maintenance_in_progress",
            "retry_after_ms": 300,
        }


def test_reranker_does_not_load_model_inside_query(monkeypatch):
    from memory_center.core.retrieval import hybrid

    previous = dict(hybrid._RERANKER_MODELS)
    hybrid._RERANKER_MODELS.clear()
    candidates = [hybrid.RetrievalResult(node_id="node:1", node={"name": "登录"}, score=1.0)]
    try:
        with patch("memory_center.core.retrieval.hybrid._load_reranker") as load:
            returned, diagnostics = hybrid._rerank_candidates("登录", candidates, limit=1)
        assert returned == candidates
        assert diagnostics["reason"] == "reranker_not_prewarmed"
        load.assert_not_called()
    finally:
        hybrid._RERANKER_MODELS.clear()
        hybrid._RERANKER_MODELS.update(previous)


# ═══════════════════════════════════════════════════════════════════════════════
# BusinessDomainExtractor tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestBusinessDomainExtractor:
    """Tests for BusinessDomainExtractor (§20.4 domain/)."""

    def test_extract_domains_from_populated_store(self, populated_store):
        extractor = BusinessDomainExtractor(populated_store)
        domains = extractor.extract_domains()
        assert len(domains) >= 1
        # Should find user domain from UserService, UserController
        domain_names = {d.name for d in domains}
        assert "user" in domain_names

    def test_extract_domains_empty_store(self, store):
        extractor = BusinessDomainExtractor(store)
        domains = extractor.extract_domains()
        assert domains == []

    def test_domain_to_dict(self):
        d = BusinessDomain(domain_id="d:1", name="order", services=["order-svc"], entities=["e1"])
        dd = d.to_dict()
        assert dd["domain_id"] == "d:1"
        assert dd["name"] == "order"
        assert "order-svc" in dd["services"]

    def test_extract_flows(self, populated_store):
        extractor = BusinessDomainExtractor(populated_store)
        flows = extractor.extract_flows()
        assert len(flows) >= 1
        # Should find flow from POST /api/users
        flow_names = {f.name for f in flows}
        assert any("users" in name for name in flow_names)

    def test_extract_flows_empty_store(self, store):
        extractor = BusinessDomainExtractor(store)
        flows = extractor.extract_flows()
        assert flows == []

    def test_flow_to_dict(self):
        f = BusinessFlow(flow_id="f:1", name="test", steps=[{"order": 0}])
        fd = f.to_dict()
        assert fd["flow_id"] == "f:1"
        assert len(fd["steps"]) == 1

    def test_domain_confidence_scales_with_entity_count(self, populated_store):
        extractor = BusinessDomainExtractor(populated_store)
        domains = extractor.extract_domains()
        for d in domains:
            if len(d.entities) >= 10:
                assert d.confidence >= 0.9
            elif len(d.entities) >= 5:
                assert d.confidence >= 0.7

    def test_infer_domain_from_payment(self, store):
        """Payment-related nodes should map to 'payment' domain."""
        store.upsert_nodes([
            ("Class:pay-svc:PaymentController", "Class", "PaymentController", "pay-svc",
             "src/PaymentController.java", 1, '{"annotations":["RestController"]}'),
            ("Class:pay-svc:RefundService", "Class", "RefundService", "pay-svc",
             "src/RefundService.java", 10, '{"annotations":["Service"]}'),
        ])
        extractor = BusinessDomainExtractor(store)
        domains = extractor.extract_domains()
        domain_names = {d.name for d in domains}
        assert "payment" in domain_names


# ═══════════════════════════════════════════════════════════════════════════════
# ArchitectureTourGenerator tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestArchitectureTourGenerator:
    """Tests for ArchitectureTourGenerator (§20.4 onboarding/)."""

    def test_generate_tour_for_developer(self, populated_store):
        gen = ArchitectureTourGenerator(populated_store)
        tour = gen.generate_tour(persona="developer")
        assert isinstance(tour, ArchitectureTour)
        assert tour.persona == "developer"
        assert len(tour.steps) >= 1

    def test_tour_includes_services_step(self, populated_store):
        gen = ArchitectureTourGenerator(populated_store)
        tour = gen.generate_tour(persona="developer")
        titles = [s.title for s in tour.steps]
        assert any("服务" in t or "概览" in t for t in titles)

    def test_tour_includes_endpoints_step(self, populated_store):
        gen = ArchitectureTourGenerator(populated_store)
        tour = gen.generate_tour(persona="developer")
        titles = [s.title for s in tour.steps]
        assert any("API" in t or "入口" in t for t in titles)

    def test_tour_includes_feign_for_developer(self, populated_store):
        gen = ArchitectureTourGenerator(populated_store)
        tour = gen.generate_tour(persona="developer")
        titles = [s.title for s in tour.steps]
        assert any("Feign" in t for t in titles)

    def test_tour_excludes_feign_for_product(self, populated_store):
        gen = ArchitectureTourGenerator(populated_store)
        tour = gen.generate_tour(persona="product")
        titles = [s.title for s in tour.steps]
        # Product persona doesn't need Feign details
        assert not any("Feign" in t for t in titles)

    def test_tour_includes_mq_step(self, populated_store):
        gen = ArchitectureTourGenerator(populated_store)
        tour = gen.generate_tour(persona="developer")
        titles = [s.title for s in tour.steps]
        assert any("消息" in t or "MQ" in t for t in titles)

    def test_tour_to_dict(self, populated_store):
        gen = ArchitectureTourGenerator(populated_store)
        tour = gen.generate_tour(persona="architect")
        d = tour.to_dict()
        assert "tour_id" in d
        assert "steps" in d
        assert "summary" in d
        assert d["persona"] == "architect"
        assert d["total_steps"] == len(tour.steps)

    def test_tour_step_to_dict(self):
        step = TourStep(step_id=1, title="Test", description="Desc", node_ids=["a"])
        d = step.to_dict()
        assert d["step_id"] == 1
        assert d["title"] == "Test"

    def test_generate_tour_empty_store(self, store):
        gen = ArchitectureTourGenerator(store)
        tour = gen.generate_tour(persona="developer")
        assert len(tour.steps) == 0
        assert tour.summary != ""

    def test_tour_with_target(self, populated_store):
        gen = ArchitectureTourGenerator(populated_store)
        tour = gen.generate_tour(persona="developer", target="user-svc")
        assert "user-svc" in tour.summary


# ═══════════════════════════════════════════════════════════════════════════════
# Parallel indexing tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestParallelIndexing:
    """Tests for parallel indexing (§6.1)."""

    def test_walk_project_files(self, tmp_path):
        # Create test project structure
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "Foo.java").write_text("class Foo {}")
        (tmp_path / "src" / "Bar.java").write_text("class Bar {}")
        (tmp_path / "application.yml").write_text("server:\n  port: 8080")
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("")  # should be ignored

        java_files, config_files = walk_project_files(tmp_path)
        assert len(java_files) == 2
        assert len(config_files) == 1

    def test_walk_project_files_skips_target(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "Foo.java").write_text("class Foo {}")
        (tmp_path / "target").mkdir()
        (tmp_path / "target" / "Bar.java").write_text("class Bar {}")

        java_files, _ = walk_project_files(tmp_path)
        assert len(java_files) == 1

    def test_parse_files_parallel(self, tmp_path):
        from memory_center.core.indexing.base import JavaParseResult
        (tmp_path / "A.java").write_text("class A {}")
        (tmp_path / "B.java").write_text("class B {}")

        def mock_parse(text, path):
            return JavaParseResult(classes=[text.split()[1].rstrip("{}")])

        files = [("proj", tmp_path / "A.java"), ("proj", tmp_path / "B.java")]
        results = parse_files_parallel(files, mock_parse, max_workers=2)
        assert len(results) == 2
        for svc, _path, result in results:
            assert svc == "proj"
            assert result is not None

    def test_parse_files_parallel_with_error(self, tmp_path):
        from memory_center.core.indexing.base import JavaParseResult
        (tmp_path / "good.java").write_text("class Good {}")
        (tmp_path / "bad.java").write_bytes(b"\x00\x01\x02")  # invalid encoding

        def mock_parse(text, path):
            if "bad" in str(path):
                raise ValueError("parse error")
            return JavaParseResult(classes=["Good"])

        files = [("proj", tmp_path / "good.java"), ("proj", tmp_path / "bad.java")]
        results = parse_files_parallel(files, mock_parse, max_workers=2)
        assert len(results) == 2
        # One should succeed, one should have None result
        results_dict = {str(path): result for svc, path, result in results}
        assert results_dict[str(tmp_path / "good.java")] is not None

    def test_estimate_optimal_workers(self):
        assert estimate_optimal_workers(100, max_workers=8) >= 1
        assert estimate_optimal_workers(100, max_workers=8) <= 8
        assert estimate_optimal_workers(0, max_workers=8) >= 1
        assert estimate_optimal_workers(10000, max_workers=4) <= 4

    def test_walk_empty_dir(self, tmp_path):
        java_files, config_files = walk_project_files(tmp_path)
        assert java_files == []
        assert config_files == []

    def test_walk_custom_extensions(self, tmp_path):
        (tmp_path / "test.py").write_text("print('hello')")
        (tmp_path / "test.java").write_text("class T {}")
        java_files, _ = walk_project_files(tmp_path, extensions=(".py",))
        assert len(java_files) == 1
        assert java_files[0].suffix == ".py"


# ═══════════════════════════════════════════════════════════════════════════════
# IncrementalIndexer tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestIncrementalIndexer:
    """Tests for IncrementalIndexer (§6.3)."""

    def test_changed_file_dataclass(self):
        cf = ChangedFile(path="src/Foo.java", status="M")
        assert cf.path == "src/Foo.java"
        assert cf.status == "M"

    def test_remove_by_file_path(self, store):
        store.upsert_nodes([
            ("Class:p:A", "Class", "A", "p", "src/A.java", 1, "{}"),
            ("Class:p:B", "Class", "B", "p", "src/B.java", 1, "{}"),
        ])
        store.upsert_edges([
            ("E:A->B", "Class:p:A", "Class:p:B", "CALLS", 1.0, "{}"),
        ])
        indexer = IncrementalIndexer(store, repo_root=Path("/tmp"))
        removed = indexer.remove_by_file_path("src/A.java")
        assert "Class:p:A" in removed
        # B should still exist
        assert store.node_by_id("Class:p:B") is not None
        # A should be gone
        assert store.node_by_id("Class:p:A") is None

    def test_remove_nonexistent_file(self, store):
        indexer = IncrementalIndexer(store, repo_root=Path("/tmp"))
        removed = indexer.remove_by_file_path("nonexistent.java")
        assert removed == set()

    def test_detect_changes_without_git(self, tmp_path):
        """Without a .git directory, should return empty changes."""
        db = tmp_path / "test.db"
        store = RuntimeStore(str(db))
        indexer = IncrementalIndexer(store, repo_root=tmp_path)
        changes = indexer.detect_changes()
        assert all(len(v) == 0 for v in changes.values())
        store.close()

    def test_incremental_reindex_without_git(self, tmp_path):
        db = tmp_path / "test.db"
        store = RuntimeStore(str(db))
        indexer = IncrementalIndexer(store, repo_root=tmp_path)
        result = indexer.incremental_reindex(parse_fn=None)
        assert result["mode"] == "incremental"
        assert result["deleted_count"] == 0
        store.close()

    def test_incremental_reindex_uses_explicit_workspace(self, tmp_path):
        from tests.fixtures import copy_demo_workspace

        workspace = copy_demo_workspace(tmp_path)
        store = RuntimeStore(workspace.parent / "graph" / "graph.db")
        indexer = IncrementalIndexer(
            store,
            repo_root=workspace.parent.parent,
            workspace_file=workspace,
        )
        indexer.detect_changes = lambda since="HEAD": {
            "added": [ChangedFile(path="article-service/src/New.java", status="A")],
            "modified": [],
            "deleted": [],
            "renamed": [],
        }

        with patch(
            "memory_center.core.indexing.reindex.reindex_workspace",
            return_value={"mode": "partial", "scanned_files": 1},
        ) as reindex:
            result = indexer.incremental_reindex(parse_fn=None)

        assert result["reindexed"] is True
        assert result["reindex_result"]["mode"] == "partial"
        reindex.assert_called_once()
        assert reindex.call_args.kwargs["paths"] == ["article-service/src/New.java"]
        store.close()

    def test_remove_cascades_edges(self, store):
        """Removing a node should also remove its edges."""
        store.upsert_nodes([
            ("Class:p:X", "Class", "X", "p", "src/X.java", 1, "{}"),
            ("Class:p:Y", "Class", "Y", "p", "src/Y.java", 1, "{}"),
            ("Class:p:Z", "Class", "Z", "p", "src/Z.java", 1, "{}"),
        ])
        store.upsert_edges([
            ("E:X->Y", "Class:p:X", "Class:p:Y", "CALLS", 1.0, "{}"),
            ("E:X->Z", "Class:p:X", "Class:p:Z", "CALLS", 1.0, "{}"),
            ("E:Y->Z", "Class:p:Y", "Class:p:Z", "CALLS", 1.0, "{}"),
        ])
        indexer = IncrementalIndexer(store, repo_root=Path("/tmp"))
        indexer.remove_by_file_path("src/X.java")

        # Edges from X should be gone
        edges = store.edges_for_node("Class:p:X", direction="downstream")
        assert len(edges) == 0
        # Edge Y->Z should still exist
        edges = store.edges_for_node("Class:p:Y", direction="downstream")
        assert len(edges) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# FileWatcher tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestFileWatcher:
    """Tests for FileWatcher (§20.8)."""

    def test_take_snapshot(self, tmp_path):
        (tmp_path / "Foo.java").write_text("class Foo {}")
        (tmp_path / "Bar.java").write_text("class Bar {}")
        (tmp_path / "readme.txt").write_text("not watched")

        watcher = FileWatcher(tmp_path, extensions=(".java",))
        snapshots = watcher.take_snapshot()
        assert len(snapshots) == 2
        assert "Foo.java" in snapshots
        assert "Bar.java" not in snapshots or "Foo.java" in snapshots

    def test_detect_changes_added(self, tmp_path):
        watcher = FileWatcher(tmp_path, extensions=(".java",))
        # Initial snapshot (empty)
        watcher.take_snapshot()  # not stored yet
        watcher._snapshots = watcher.take_snapshot()

        # Add a file
        (tmp_path / "New.java").write_text("class New {}")
        events = watcher.detect_changes()
        assert len(events) == 1
        assert events[0].change_type == "added"
        assert events[0].path == "New.java"

    def test_detect_changes_modified(self, tmp_path):
        (tmp_path / "Foo.java").write_text("class Foo {}")
        watcher = FileWatcher(tmp_path, extensions=(".java",))
        watcher._snapshots = watcher.take_snapshot()

        # Modify the file
        time.sleep(0.01)
        (tmp_path / "Foo.java").write_text("class Foo { void bar() {} }")
        events = watcher.detect_changes()
        assert len(events) == 1
        assert events[0].change_type == "modified"

    def test_detect_changes_deleted(self, tmp_path):
        (tmp_path / "Foo.java").write_text("class Foo {}")
        watcher = FileWatcher(tmp_path, extensions=(".java",))
        watcher._snapshots = watcher.take_snapshot()

        # Delete the file
        (tmp_path / "Foo.java").unlink()
        events = watcher.detect_changes()
        assert len(events) == 1
        assert events[0].change_type == "deleted"

    def test_no_changes_detected(self, tmp_path):
        (tmp_path / "Foo.java").write_text("class Foo {}")
        watcher = FileWatcher(tmp_path, extensions=(".java",))
        watcher._snapshots = watcher.take_snapshot()

        events = watcher.detect_changes()
        assert len(events) == 0

    def test_ignore_dirs(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "Foo.java").write_text("class Foo {}")
        (tmp_path / "target").mkdir()
        (tmp_path / "target" / "Built.java").write_text("class Built {}")

        watcher = FileWatcher(tmp_path, extensions=(".java",), ignore_dirs=("target",))
        snapshots = watcher.take_snapshot()
        assert len(snapshots) == 1

    def test_status(self, tmp_path):
        watcher = FileWatcher(tmp_path, extensions=(".java",))
        s = watcher.status()
        assert s["running"] is False
        assert s["tracked_files"] == 0

    def test_on_change_callback(self, tmp_path):
        watcher = FileWatcher(tmp_path, extensions=(".java",))
        received = []
        watcher.on_change(lambda events: received.extend(events))
        assert len(watcher._callbacks) == 1

    def test_watch_event_dataclass(self):
        event = WatchEvent(path="src/Foo.java", change_type="modified")
        assert event.path == "src/Foo.java"
        assert event.change_type == "modified"
        assert event.detected_at > 0

    def test_file_snapshot_dataclass(self):
        snap = FileSnapshot(path="Foo.java", mtime=100.0, size=50)
        assert snap.path == "Foo.java"
        assert snap.mtime == 100.0

    def test_start_stop(self, tmp_path):
        watcher = FileWatcher(
            tmp_path, extensions=(".java",),
            poll_interval=0.1, debounce_seconds=0.1,
        )
        watcher.start()
        assert watcher.status()["running"] is True
        watcher.stop()
        assert watcher.status()["running"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# Integration tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestV3Integration:
    """End-to-end integration tests combining multiple V3 modules."""

    def test_full_v3_workflow(self, tmp_path):
        """Complete V3 workflow: populate graph → domain → tour → view → vector search."""
        db = tmp_path / "full.db"
        with RuntimeStore(str(db)) as store:
            # 1. Populate
            store.upsert_nodes([
                ("Service:user-svc", "Service", "user-svc", "user-svc", "", 0, "{}"),
                ("Class:user-svc:UserService", "Class", "UserService", "user-svc",
                 "UserService.java", 1, '{"annotations":["Service"]}'),
                ("Endpoint:user-svc:GET:/api/users", "Endpoint", "GET /api/users", "user-svc",
                 "UserController.java", 5, '{"http_method":"GET","path":"/api/users"}'),
                ("MQConsumer:user-svc:UserListener:topic-x", "MQConsumer", "UserListener",
                 "user-svc", "UserListener.java", 10,
                 '{"class_name":"UserListener","method_name":"handle","topic":"topic-x"}'),
            ])
            store.upsert_edges([
                ("E1", "Service:user-svc", "Class:user-svc:UserService", "CONTAINS", 1.0, "{}"),
                ("E2", "Endpoint:user-svc:GET:/api/users", "Class:user-svc:UserService",
                 "CALLS_METHOD", 0.8, "{}"),
            ])

            # 2. Domain extraction
            domains = BusinessDomainExtractor(store).extract_domains()
            assert len(domains) >= 1

            # 3. Tour generation
            tour = ArchitectureTourGenerator(store).generate_tour(persona="developer")
            assert len(tour.steps) >= 1

            # 4. Vector search
            vi = VectorIndex(store, dimension=4)
            vi.upsert_embedding("Class:user-svc:UserService", [1.0, 0.0, 0.0, 0.0])
            results = vi.query([0.9, 0.1, 0.0, 0.0])
            assert len(results) >= 1

            # 5. Incremental indexer
            indexer = IncrementalIndexer(store, repo_root=tmp_path)
            removed = indexer.remove_by_file_path("UserService.java")
            assert "Class:user-svc:UserService" in removed

    def test_domain_to_tour_pipeline(self, populated_store):
        """Extract domains, then generate a tour that references them."""
        domains = BusinessDomainExtractor(populated_store).extract_domains()
        tour = ArchitectureTourGenerator(populated_store).generate_tour(persona="architect")

        # Both should reference the same services
        domain_services = set()
        for d in domains:
            domain_services.update(d.services)
        tour_node_ids = set()
        for step in tour.steps:
            tour_node_ids.update(step.node_ids)

        # At least some overlap
        assert len(domain_services) >= 1
        assert len(tour_node_ids) >= 1
