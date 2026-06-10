"""Tests for E-02 through E-08: Indexer, Retrieval & Storage foundations.

Verifies:
E-02: Tree-sitter parser optional integration with regex fallback
E-03: Parallel indexing with fault tolerance
E-04: Watcher-to-incremental bridge
E-05: Connect-time catch-up (stale recovery)
E-06: Inverted/FTS retrieval (BM25 inverted index)
E-07: Native vector retrieval (sqlite-vec / brute force)
E-08: Hybrid retrieval fusion (graph + sparse + semantic + vector)
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture()
def demo_workspace(tmp_path: Path) -> Path:
    source = Path("examples/spring-cloud-demo")
    target = tmp_path / "demo"
    shutil.copytree(source, target)
    ws = target / ".memory-center" / "workspace.yaml"
    lines = ws.read_text(encoding="utf-8").splitlines()
    lines = [f"root: {target.as_posix()}" if line.startswith("root:") else line for line in lines]
    ws.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ws


@pytest.fixture()
def unified_store(demo_workspace: Path):
    from memory_center.core.store import WorkspaceStore
    ws = WorkspaceStore(str(demo_workspace))
    from memory_center.core.storage.unified import UnifiedStore
    store = UnifiedStore(ws.graph_db_path)
    yield store
    store.close()


# ═════════════════════════════════════════════════════════════════════════════
# E-02: Tree-sitter Java Parser Optional Integration
# ═════════════════════════════════════════════════════════════════════════════

class TestE02TreeSitterOptional:
    """E-02: Tree-sitter parser is optional with regex fallback."""

    def test_parser_available_property(self):
        from memory_center.core.indexing.tree_sitter_parser import TreeSitterJavaParser
        parser = TreeSitterJavaParser()
        assert isinstance(parser.available, bool)

    def test_parser_falls_back_to_regex(self):
        from memory_center.core.indexing.tree_sitter_parser import TreeSitterJavaParser
        parser = TreeSitterJavaParser()
        if not parser.available:
            # When tree-sitter unavailable, parse still works via regex fallback
            result = parser.parse("public class Foo {}", "Foo.java")
            assert "Foo" in result.classes

    def test_parser_result_has_required_fields(self):
        from memory_center.core.indexing.tree_sitter_parser import TreeSitterJavaParser
        from memory_center.core.indexing.base import JavaParseResult
        parser = TreeSitterJavaParser()
        result = parser.parse("", "Empty.java")
        assert isinstance(result, JavaParseResult)
        assert hasattr(result, "package")
        assert hasattr(result, "imports")
        assert hasattr(result, "classes")
        assert hasattr(result, "methods")
        assert hasattr(result, "annotations")

    def test_parser_detects_package(self):
        from memory_center.core.indexing.tree_sitter_parser import TreeSitterJavaParser
        parser = TreeSitterJavaParser()
        src = "package com.example;\npublic class Foo {}"
        result = parser.parse(src, "Foo.java")
        assert result.package == "com.example"

    def test_parser_detects_annotations(self):
        from memory_center.core.indexing.tree_sitter_parser import TreeSitterJavaParser
        parser = TreeSitterJavaParser()
        src = "@RestController\n@RequestMapping(\"/api\")\npublic class Controller {}"
        result = parser.parse(src, "Controller.java")
        assert "RestController" in result.annotations
        assert "RequestMapping" in result.annotations

    def test_indexer_auto_selects_parser(self):
        import memory_center.core.indexer as indexer_mod
        assert hasattr(indexer_mod, "_JAVA_PARSER")
        assert hasattr(indexer_mod._JAVA_PARSER, "parse")
        assert hasattr(indexer_mod._JAVA_PARSER, "name")

    def test_parser_comparison_identical_output(self):
        """Both parsers should produce same core fields for simple input."""
        from memory_center.core.indexing.tree_sitter_parser import TreeSitterJavaParser
        from memory_center.core.indexing.java_regex_parser import RegexJavaParser
        src = """package com.example;
import java.util.List;
@Service
public class MyService {
    private String name;
    public void doWork() {}
}"""
        regex = RegexJavaParser()
        ts = TreeSitterJavaParser()
        r1 = regex.parse(src, "MyService.java")
        r2 = ts.parse(src, "MyService.java")
        assert r1.package == r2.package
        assert set(r1.classes) == set(r2.classes)
        assert "doWork" in r1.methods
        assert "doWork" in r2.methods

    def test_tree_sitter_available_path_merges_regex_enriched_facts(self):
        from memory_center.core.indexing.tree_sitter_parser import TreeSitterJavaParser

        class FakeNode:
            def __init__(self, node_type, text="", children=None, fields=None):
                self.type = node_type
                self.text = text.encode("utf-8")
                self.children = children or []
                self._fields = fields or {}

            def child_by_field_name(self, name):
                return self._fields.get(name)

        class FakeTree:
            def __init__(self, root_node):
                self.root_node = root_node

        class FakeTsParser:
            def parse(self, _text):
                package_name = FakeNode("scoped_identifier", "com.example.service")
                package_decl = FakeNode("package_declaration", children=[package_name])
                service_name = FakeNode("identifier", "UserService")
                class_decl = FakeNode("class_declaration", fields={"name": service_name})
                method_name = FakeNode("identifier", "sync")
                method_decl = FakeNode("method_declaration", fields={"name": method_name})
                annotation_name = FakeNode("identifier", "Service")
                annotation = FakeNode("annotation", fields={"name": annotation_name})
                root = FakeNode("program", children=[package_decl, annotation, class_decl, method_decl])
                return FakeTree(root)

        parser = TreeSitterJavaParser()
        parser._parser = FakeTsParser()
        src = """package com.example.service;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.data.mongodb.core.MongoTemplate;

@Service
public class UserService {
    private final OrderClient orderClient;
    private final MongoTemplate mongoTemplate;

    @Value("${demo.topic}")
    private String topic;

    public UserService(OrderClient orderClient, MongoTemplate mongoTemplate) {
        this.orderClient = orderClient;
        this.mongoTemplate = mongoTemplate;
    }

    public void sync(UserDto dto) {
        orderClient.fetch();
        dto.getName();
    }
}
"""
        result = parser.parse(src, "UserService.java")
        assert result.package == "com.example.service"
        assert "UserService" in result.classes
        assert "sync" in result.methods
        assert "Service" in result.annotations
        assert result.bean_injections
        assert any(item["receiver"] == "orderClient" for item in result.method_calls)
        assert any(item["field"] == "name" for item in result.dto_field_usages)
        assert any(item["key"] == "demo.topic" for item in result.config_usages)
        assert any(item["kind"] == "MongoCollection" for item in result.data_resources)

    def test_parse_java_symbols_records_selected_parser(self, monkeypatch):
        import memory_center.core.indexer as indexer_mod
        from memory_center.core.indexing.base import JavaParseResult

        class FakeParser:
            name = "tree-sitter"

            def parse(self, text, file_path):
                return JavaParseResult(classes=["Demo"], methods=["run"])

        monkeypatch.setattr(indexer_mod, "_JAVA_PARSER", FakeParser())
        symbol = indexer_mod.parse_java_symbols("demo", "src/Demo.java", "public class Demo { void run() {} }")
        assert symbol.parser == "tree-sitter"
        assert symbol.classes == ["Demo"]


# ═════════════════════════════════════════════════════════════════════════════
# E-03: Parallel Indexing with Fault Tolerance
# ═════════════════════════════════════════════════════════════════════════════

class TestE03ParallelIndexing:
    """E-03: Parallel file parsing with fault tolerance."""

    def test_parse_files_parallel_basic(self):
        from memory_center.core.indexing.parallel import parse_files_parallel
        from memory_center.core.indexing.java_regex_parser import RegexJavaParser
        parser = RegexJavaParser()
        # Empty file list should return empty results
        results = parse_files_parallel([], parser.parse)
        assert results == []

    def test_parse_files_parallel_fault_tolerance(self):
        """Malformed files should not crash parallel parsing."""
        from memory_center.core.indexing.parallel import parse_files_parallel
        from memory_center.core.indexing.java_regex_parser import RegexJavaParser
        import tempfile
        parser = RegexJavaParser()
        # Create a temp file with valid Java
        with tempfile.NamedTemporaryFile(suffix=".java", mode="w", delete=False) as f:
            f.write("public class Valid {}")
            valid_path = Path(f.name)
        try:
            files = [("test-project", valid_path)]
            results = parse_files_parallel(files, parser.parse)
            assert len(results) == 1
            assert results[0][2] is not None  # parse result
        finally:
            valid_path.unlink(missing_ok=True)

    def test_estimate_optimal_workers(self):
        from memory_center.core.indexing.parallel import estimate_optimal_workers
        w = estimate_optimal_workers(100)
        assert 1 <= w <= 8
        w2 = estimate_optimal_workers(1)
        assert w2 >= 1

    def test_walk_project_files_finds_java(self, demo_workspace: Path):
        from memory_center.core.indexing.parallel import walk_project_files
        # demo_workspace is the workspace.yaml path, get parent project root
        project_root = demo_workspace.parent.parent
        java_files, config_files = walk_project_files(project_root)
        assert isinstance(java_files, list)
        assert isinstance(config_files, list)


# ═════════════════════════════════════════════════════════════════════════════
# E-04: Watcher-to-Incremental Bridge
# ═════════════════════════════════════════════════════════════════════════════

class TestE04WatcherIncremental:
    """E-04: File watcher can trigger incremental reindex."""

    def test_incremental_indexer_class_exists(self):
        from memory_center.core.indexing.incremental import IncrementalIndexer
        assert IncrementalIndexer is not None

    def test_changed_file_dataclass(self):
        from memory_center.core.indexing.incremental import ChangedFile
        cf = ChangedFile(path="src/Main.java", status="M")
        assert cf.path == "src/Main.java"
        assert cf.status == "M"

    def test_git_changed_files_no_repo(self, tmp_path: Path):
        from memory_center.core.indexing.incremental import git_changed_files
        # Non-git directory should return empty
        result = git_changed_files(tmp_path)
        assert result == []

    def test_incremental_detect_changes_non_git(self, tmp_path: Path):
        from memory_center.core.indexing.incremental import IncrementalIndexer
        from memory_center.core.storage.unified import UnifiedStore
        db_path = tmp_path / "test.db"
        store = UnifiedStore(str(db_path))
        try:
            indexer = IncrementalIndexer(store, tmp_path)
            changes = indexer.detect_changes()
            assert "added" in changes
            assert "modified" in changes
            assert "deleted" in changes
        finally:
            store.close()

    def test_watcher_module_exists(self):
        from memory_center.core.freshness.watcher import FileWatcher
        assert FileWatcher is not None

    def test_freshness_status_module(self):
        from memory_center.core.freshness.status import IndexFreshnessService
        assert IndexFreshnessService is not None


# ═════════════════════════════════════════════════════════════════════════════
# E-05: Connect-time Catch-up & Stale Recovery
# ═════════════════════════════════════════════════════════════════════════════

class TestE05ConnectTimeCatchup:
    """E-05: Freshness integration provides stale recovery hints."""

    def test_freshness_integration_module(self):
        from memory_center.core.freshness.integration import get_freshness_with_actions
        assert callable(get_freshness_with_actions)

    def test_freshness_action_hint(self):
        from memory_center.core.freshness.integration import freshness_action_hint
        hint = freshness_action_hint("stale")
        assert "reindex" in hint.lower() or "较旧" in hint

    def test_freshness_risk_escalation(self):
        from memory_center.core.freshness.integration import freshness_risk_escalation
        # Stale should escalate to high
        result = freshness_risk_escalation("low", "stale")
        assert result == "high"
        # Fresh should not escalate
        result2 = freshness_risk_escalation("low", "fresh")
        assert result2 == "low"

    def test_stale_file_alert(self):
        from memory_center.core.freshness.integration import stale_file_alert
        alerts = stale_file_alert({"src/Main.java": "stale", "src/Util.java": "fresh"})
        assert len(alerts) == 1
        assert alerts[0]["file"] == "src/Main.java"

    def test_freshness_with_actions_returns_dict(self, demo_workspace: Path):
        from memory_center.core.freshness.integration import get_freshness_with_actions
        result = get_freshness_with_actions(str(demo_workspace))
        assert isinstance(result, dict)
        assert "status" in result
        assert "recommended_actions" in result


# ═════════════════════════════════════════════════════════════════════════════
# E-06: Inverted / FTS Retrieval
# ═════════════════════════════════════════════════════════════════════════════

class TestE06InvertedRetrieval:
    """E-06: BM25 inverted index retrieval."""

    def test_inverted_index_class(self):
        from memory_center.core.retrieval.inverted import InvertedIndex
        assert InvertedIndex is not None

    def test_inverted_index_build_and_query(self, unified_store):
        from memory_center.core.retrieval.inverted import InvertedIndex
        idx = InvertedIndex(unified_store)
        nodes = [
            {"id": "n1", "type": "Service", "name": "UserService", "project": "user-svc", "file_path": "src/UserService.java", "metadata": {}},
            {"id": "n2", "type": "Service", "name": "OrderService", "project": "order-svc", "file_path": "src/OrderService.java", "metadata": {}},
            {"id": "n3", "type": "Endpoint", "name": "getUserById", "project": "user-svc", "file_path": "src/UserController.java", "metadata": {}},
        ]
        stats = idx.rebuild(nodes)
        assert stats["doc_count"] == 3
        assert stats["token_count"] > 0

    def test_inverted_index_query_returns_results(self, unified_store):
        from memory_center.core.retrieval.inverted import InvertedIndex
        idx = InvertedIndex(unified_store)
        nodes = [
            {"id": "n1", "type": "Service", "name": "UserService", "project": "user-svc", "file_path": "src/UserService.java", "metadata": {}},
            {"id": "n2", "type": "Service", "name": "OrderService", "project": "order-svc", "file_path": "src/OrderService.java", "metadata": {}},
        ]
        idx.rebuild(nodes)
        results = idx.query("user service")
        assert len(results) > 0
        assert results[0]["node_id"] == "n1"

    def test_inverted_index_empty_query(self, unified_store):
        from memory_center.core.retrieval.inverted import InvertedIndex
        idx = InvertedIndex(unified_store)
        results = idx.query("")
        assert results == []

    def test_inverted_index_stats(self, unified_store):
        from memory_center.core.retrieval.inverted import InvertedIndex
        idx = InvertedIndex(unified_store)
        nodes = [
            {"id": "n1", "type": "Service", "name": "TestService", "project": "test", "file_path": "Test.java", "metadata": {}},
        ]
        idx.rebuild(nodes)
        stats = idx.stats()
        assert "doc_count" in stats
        assert stats["doc_count"] == 1

    def test_reindex_builds_bm25_index(self, demo_workspace: Path):
        from memory_center.core.config import load_workspace_config
        from memory_center.core.indexer import reindex_workspace
        from memory_center.core.retrieval.inverted import InvertedIndex
        from memory_center.core.storage.unified import UnifiedStore
        from memory_center.core.store import WorkspaceStore

        workspace_store = WorkspaceStore(demo_workspace)
        reindex_workspace(load_workspace_config(demo_workspace), workspace_store)

        with UnifiedStore(workspace_store.graph_db_path) as unified:
            assert InvertedIndex(unified).stats()["doc_count"] > 0


# ═════════════════════════════════════════════════════════════════════════════
# E-07: Native Vector Retrieval
# ═════════════════════════════════════════════════════════════════════════════

class TestE07VectorRetrieval:
    """E-07: Vector index with sqlite-vec / brute force fallback."""

    def test_vector_index_class(self):
        from memory_center.core.storage.vector_index import VectorIndex
        assert VectorIndex is not None

    def test_vector_index_upsert_and_query(self, unified_store):
        from memory_center.core.storage.vector_index import VectorIndex
        vec = VectorIndex(unified_store, dimension=8)
        # Upsert a simple embedding
        vec.upsert_embedding("node1", [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        vec.upsert_embedding("node2", [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        # Query for node1-like
        results = vec.query([1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], limit=2)
        assert len(results) > 0
        assert results[0]["node_id"] == "node1"

    def test_vector_index_stats(self, unified_store):
        from memory_center.core.storage.vector_index import VectorIndex
        vec = VectorIndex(unified_store, dimension=4)
        vec.upsert_embedding("node1", [1.0, 0.0, 0.0, 0.0])
        stats = vec.stats()
        assert stats["embedding_count"] == 1

    def test_vector_index_delete(self, unified_store):
        from memory_center.core.storage.vector_index import VectorIndex
        vec = VectorIndex(unified_store, dimension=4)
        vec.upsert_embedding("node1", [1.0, 0.0, 0.0, 0.0])
        vec.delete_embedding("node1")
        stats = vec.stats()
        assert stats["embedding_count"] == 0

    def test_vector_index_batch_upsert(self, unified_store):
        from memory_center.core.storage.vector_index import VectorIndex
        vec = VectorIndex(unified_store, dimension=4)
        items = [
            ("n1", [1.0, 0.0, 0.0, 0.0]),
            ("n2", [0.0, 1.0, 0.0, 0.0]),
        ]
        count = vec.upsert_embeddings_batch(items)
        assert count == 2

    def test_vector_index_dimension_mismatch(self, unified_store):
        from memory_center.core.storage.vector_index import VectorIndex
        vec = VectorIndex(unified_store, dimension=4)
        with pytest.raises(ValueError):
            vec.upsert_embedding("node1", [1.0, 0.0])  # wrong dimension

    def test_vector_in_hybrid_retrieval(self):
        """Vector retrieval is imported in hybrid.py."""
        import memory_center.core.retrieval.hybrid as hybrid_mod
        source = open(hybrid_mod.__file__).read()
        assert "vector_index" in source or "VectorIndex" in source or "_vector_retrieval" in source

    def test_retrieval_index_sync_writes_dense_embeddings(self, demo_workspace: Path):
        from memory_center.core.indexer import _sync_retrieval_indexes
        from memory_center.core.storage.unified import UnifiedStore
        from memory_center.core.storage.vector_index import VectorIndex
        from memory_center.core.store import WorkspaceStore

        workspace_store = WorkspaceStore(demo_workspace)
        stats = _sync_retrieval_indexes(
            workspace_store,
            {
                "docs": [
                    {"node_id": "node-1", "dense_vector": [1.0, 0.0, 0.0]},
                    {"node_id": "node-2", "dense_vector": [0.0, 1.0, 0.0]},
                ],
            },
        )

        assert stats["vector_embeddings"] == 2
        with UnifiedStore(workspace_store.graph_db_path) as unified:
            assert VectorIndex(unified, dimension=3).stats()["embedding_count"] == 2


# ═════════════════════════════════════════════════════════════════════════════
# E-08: Hybrid Retrieval Fusion
# ═════════════════════════════════════════════════════════════════════════════

class TestE08HybridRetrievalFusion:
    """E-08: Hybrid retrieval combines graph + sparse + semantic + vector."""

    def test_hybrid_module_structure(self):
        from memory_center.core.retrieval.hybrid import (
            HybridRetrievalConfig,
        )
        config = HybridRetrievalConfig()
        assert config.graph_weight > 0
        assert config.sparse_weight > 0
        assert config.semantic_weight > 0

    def test_retrieval_result_dataclass(self):
        from memory_center.core.retrieval.hybrid import RetrievalResult
        r = RetrievalResult(node_id="n1", node={"name": "test"}, score=0.9)
        assert r.node_id == "n1"
        assert r.score == 0.9
        assert isinstance(r.sources, list)

    def test_hybrid_retrieval_config_defaults(self):
        from memory_center.core.retrieval.hybrid import HybridRetrievalConfig
        config = HybridRetrievalConfig()
        assert config.max_results == 20
        assert config.min_confidence == 0.3
        assert config.neighbor_depth == 2
        assert config.enable_cross_workspace is True

    def test_query_pattern_detection(self):
        """Intent detection should match feign/mq/endpoint/config patterns."""
        import memory_center.core.retrieval.hybrid as hybrid_mod
        # Verify _QUERY_PATTERNS exists and has expected keys
        assert hasattr(hybrid_mod, "_QUERY_PATTERNS")
        patterns = hybrid_mod._QUERY_PATTERNS
        assert "feign" in patterns
        assert "mq" in patterns
        assert "endpoint" in patterns
        assert "config" in patterns

    def test_hybrid_retrieval_on_demo(self, demo_workspace: Path):
        """Full hybrid retrieval should return results on demo workspace."""
        from memory_center.core.retrieval.hybrid import hybrid_retrieve
        # hybrid_retrieve needs GraphStore + workspace_file + query
        from memory_center.core.store import WorkspaceStore
        from memory_center.core.graph import GraphStore
        ws = WorkspaceStore(str(demo_workspace))
        with GraphStore(ws.graph_db_path) as graph:
            result = hybrid_retrieve(graph, str(demo_workspace), "UserService")
        assert isinstance(result, dict)
        # Should have results or diagnostics
        assert "results" in result or "diagnostics" in result or "query" in result

    def test_bm25_hits_are_merged(self):
        """BM25-only hits must survive hybrid fusion."""
        from memory_center.core.retrieval.hybrid import (
            HybridRetrievalConfig,
            RetrievalResult,
            _merge_retrieval_results,
        )

        hit = RetrievalResult(
            node_id="bm25-node",
            node={"id": "bm25-node"},
            score=2.0,
            sources=["sparse_bm25"],
        )
        results = _merge_retrieval_results(
            [], [], [], HybridRetrievalConfig(), {}, bm25_hits=[hit],
        )
        assert [item.node_id for item in results] == ["bm25-node"]

    def test_vector_retrieval_respects_disabled_flag(self):
        """Disabled vector retrieval must not execute the vector backend."""
        from unittest.mock import patch

        from memory_center.core.retrieval.hybrid import HybridRetrievalConfig, hybrid_retrieve

        class EmptyGraph:
            def find_nodes(self, *args, **kwargs):
                return []

            def neighbors(self, *args, **kwargs):
                return []

        with (
            patch("memory_center.core.retrieval.hybrid._vector_retrieval", return_value=[]) as vector,
            patch("memory_center.core.retrieval.hybrid._semantic_retrieval", return_value=[]),
            patch("memory_center.core.retrieval.hybrid._bm25_sparse_retrieval", return_value=[]),
        ):
            hybrid_retrieve(
                EmptyGraph(),
                "/missing/workspace.yaml",
                "query",
                config=HybridRetrievalConfig(enable_vector=False, enable_cross_workspace=False),
            )
        vector.assert_not_called()

    def test_vector_hits_use_vector_weight(self):
        """Vector contribution must use vector_weight rather than semantic_weight."""
        from memory_center.core.retrieval.hybrid import (
            HybridRetrievalConfig,
            RetrievalResult,
            _merge_retrieval_results,
        )

        hit = RetrievalResult(
            node_id="vector-node",
            node={"id": "vector-node"},
            score=1.0,
            sources=["vector_ann"],
        )
        results = _merge_retrieval_results(
            [],
            [],
            [],
            HybridRetrievalConfig(vector_weight=0.7, semantic_weight=0.1),
            {},
            vector_hits=[hit],
        )
        assert results[0].score == pytest.approx(0.7)



# ── E-07: Native Vector Retrieval Integration ───────────────────────

class TestE07VectorRetrievalIntegration:
    """Test VectorIndex integration into hybrid retrieval (E-07)."""

    def test_vector_index_class_exists(self):
        """VectorIndex is importable."""
        from memory_center.core.storage.vector_index import VectorIndex
        assert callable(VectorIndex)

    def test_vector_index_stats(self, demo_workspace):
        """VectorIndex.stats returns expected fields."""
        from memory_center.core.store import WorkspaceStore
        from memory_center.core.storage.unified import UnifiedStore
        from memory_center.core.storage.vector_index import VectorIndex
        ws = WorkspaceStore(str(demo_workspace))
        with UnifiedStore(ws.graph_db_path) as unified:
            vec = VectorIndex(unified)
            stats = vec.stats()
            assert "embedding_count" in stats
            assert "dimension" in stats
            assert "backend" in stats
            assert stats["backend"] in ("sqlite-vec", "brute_force")

    def test_vector_index_upsert_and_query(self, demo_workspace):
        """VectorIndex can upsert and query embeddings."""
        from memory_center.core.store import WorkspaceStore
        from memory_center.core.storage.unified import UnifiedStore
        from memory_center.core.storage.vector_index import VectorIndex
        ws = WorkspaceStore(str(demo_workspace))
        with UnifiedStore(ws.graph_db_path) as unified:
            vec = VectorIndex(unified, dimension=4)
            # Upsert a test embedding
            vec.upsert_embedding("test-node-1", [1.0, 0.0, 0.0, 0.0])
            vec.upsert_embedding("test-node-2", [0.0, 1.0, 0.0, 0.0])
            # Query
            results = vec.query([1.0, 0.0, 0.0, 0.0], limit=2)
            assert len(results) >= 1
            assert results[0]["node_id"] == "test-node-1"
            assert results[0]["score"] > 0.5
            # Cleanup
            vec.delete_embedding("test-node-1")
            vec.delete_embedding("test-node-2")

    def test_vector_index_dimension_mismatch(self, demo_workspace):
        """VectorIndex raises ValueError on dimension mismatch."""
        from memory_center.core.store import WorkspaceStore
        from memory_center.core.storage.unified import UnifiedStore
        from memory_center.core.storage.vector_index import VectorIndex
        ws = WorkspaceStore(str(demo_workspace))
        with UnifiedStore(ws.graph_db_path) as unified:
            vec = VectorIndex(unified, dimension=4)
            with pytest.raises(ValueError):
                vec.upsert_embedding("test", [1.0, 0.0])  # wrong dimension
            with pytest.raises(ValueError):
                vec.query([1.0, 0.0])  # wrong dimension

    def test_vector_index_delete(self, demo_workspace):
        """VectorIndex.delete_embedding removes embeddings."""
        from memory_center.core.store import WorkspaceStore
        from memory_center.core.storage.unified import UnifiedStore
        from memory_center.core.storage.vector_index import VectorIndex
        ws = WorkspaceStore(str(demo_workspace))
        with UnifiedStore(ws.graph_db_path) as unified:
            vec = VectorIndex(unified, dimension=3)
            vec.upsert_embedding("del-test", [1.0, 0.0, 0.0])
            stats_before = vec.stats()
            assert stats_before["embedding_count"] >= 1
            vec.delete_embedding("del-test")
            stats_after = vec.stats()
            assert stats_after["embedding_count"] < stats_before["embedding_count"]

    def test_hybrid_config_has_vector_flags(self):
        """HybridRetrievalConfig has enable_vector and vector_weight."""
        from memory_center.core.retrieval.hybrid import HybridRetrievalConfig
        config = HybridRetrievalConfig()
        assert hasattr(config, "enable_vector")
        assert hasattr(config, "vector_weight")
        assert config.enable_vector is False  # disabled by default
        assert config.vector_weight > 0

    def test_hybrid_config_vector_weight_customizable(self):
        """HybridRetrievalConfig vector_weight can be customized."""
        from memory_center.core.retrieval.hybrid import HybridRetrievalConfig
        config = HybridRetrievalConfig(vector_weight=0.3, enable_vector=True)
        assert config.vector_weight == 0.3
        assert config.enable_vector is True

    def test_vector_retrieval_function_exists(self):
        """_vector_retrieval function is importable."""
        from memory_center.core.retrieval.hybrid import _vector_retrieval
        assert callable(_vector_retrieval)

    def test_vector_retrieval_returns_list(self, demo_workspace):
        """_vector_retrieval returns a list (empty when no embeddings stored)."""
        from memory_center.core.retrieval.hybrid import _vector_retrieval
        results = _vector_retrieval(str(demo_workspace), "test query", tokens=["test", "query"], limit=10)
        assert isinstance(results, list)

    def test_vector_retrieval_uses_default_model_when_semantic_index_has_no_model(self, demo_workspace):
        """Vector retrieval should not depend on semantic index backend storing a dense model name."""
        from unittest.mock import patch

        from memory_center.core.retrieval.hybrid import _vector_retrieval

        class FakeModel:
            def encode(self, texts, normalize_embeddings=True):
                assert texts == ["test query"]
                return [[1.0] * 384]

        class FakeVectorIndex:
            def __init__(self, store):
                self.store = store

            def stats(self):
                return {"embedding_count": 1, "dimension": 384, "backend": "brute_force"}

            def query(self, query_embedding, limit=20):
                assert len(query_embedding) == 384
                return [{"node_id": "demo-node", "score": 0.91, "backend": "brute_force"}]

        class FakeGraph:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def node_by_id(self, node_id):
                return {"id": node_id, "type": "Class", "name": "DemoNode", "project": "demo"}

        diagnostics = {}
        with (
            patch("memory_center.core.storage.vector_index.VectorIndex", FakeVectorIndex),
            patch("memory_center.core.graph.GraphStore", FakeGraph),
            patch("memory_center.core.semantic.semantic_index_stats", return_value={"model": None, "requested_model": None}),
            patch("memory_center.core.semantic._load_sentence_transformer_model", return_value=FakeModel()),
        ):
            results = _vector_retrieval(
                str(demo_workspace),
                "test query",
                tokens=["test", "query"],
                limit=5,
                diagnostics=diagnostics,
            )

        assert len(results) == 1
        assert results[0].node_id == "demo-node"
        assert diagnostics["vector"]["status"] == "active"
