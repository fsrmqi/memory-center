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
import yaml

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
    from memory_center.core.storage.workspace import WorkspaceStore
    ws = WorkspaceStore(str(demo_workspace))
    from memory_center.core.storage.runtime import RuntimeStore
    store = RuntimeStore(ws.graph_db_path)
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
        from memory_center.core.indexing.base import JavaParseResult
        from memory_center.core.indexing.tree_sitter_parser import TreeSitterJavaParser
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
        import memory_center.core.indexing.reindex as indexer_mod
        assert hasattr(indexer_mod, "_JAVA_PARSER")
        assert hasattr(indexer_mod._JAVA_PARSER, "parse")
        assert hasattr(indexer_mod._JAVA_PARSER, "name")

    def test_parser_comparison_identical_output(self):
        """Both parsers should produce same core fields for simple input."""
        from memory_center.core.indexing.java_regex_parser import RegexJavaParser
        from memory_center.core.indexing.tree_sitter_parser import TreeSitterJavaParser
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
        import memory_center.core.indexing.reindex as indexer_mod
        from memory_center.core.indexing.base import JavaParseResult

        class FakeParser:
            name = "tree-sitter"

            def parse(self, text, file_path):
                return JavaParseResult(classes=["Demo"], methods=["run"])

        monkeypatch.setattr(indexer_mod, "_JAVA_PARSER", FakeParser())
        symbol = indexer_mod.parse_java_symbols("demo", "src/Demo.java", "public class Demo { void run() {} }")
        assert symbol.parser == "tree-sitter"
        assert symbol.classes == ["Demo"]

    def test_regex_parser_emits_declaration_lines(self):
        from memory_center.core.indexing.java_regex_parser import RegexJavaParser

        src = """package com.example;

public class DemoService {
    private String value;

    public void run() {
    }
}
"""
        result = RegexJavaParser().parse(src, "DemoService.java")
        assert result.class_lines["DemoService"] == 3
        assert result.field_lines["value"] == 4
        assert result.method_lines["run"] == 6

    def test_detect_query_intent_prefers_class_for_single_symbol_queries(self):
        from memory_center.core.retrieval.hybrid import detect_query_intent

        # "InstructTaskController" ends with "Controller" → endpoint intent
        intent = detect_query_intent("InstructTaskController")
        assert intent["primary_intent"] == "endpoint"
        assert intent["prefer_class_symbol"] is True

    def test_detect_query_intent_prefers_class_for_service_impl_queries(self):
        from memory_center.core.retrieval.hybrid import detect_query_intent

        # "OrderServiceImpl" ends with "ServiceImpl" → class intent
        intent = detect_query_intent("OrderServiceImpl")
        assert intent["primary_intent"] == "class"
        assert intent["prefer_class_symbol"] is True

    def test_symbol_rerank_prefers_same_file_contract_and_methods_before_remote_fields(self):
        from memory_center.core.orchestrator.query import _rerank_symbol_like_matches

        items = [
            {
                "node": {
                    "id": "Field:other:FooService:remoteBizIdService",
                    "type": "Field",
                    "name": "FooService.remoteBizIdService",
                    "project": "other-service",
                    "file_path": "other/FooService.java",
                    "line": 12,
                },
                "score": 1.4,
                "sources": ["graph_exact", "sparse_fts", "sparse_bm25"],
            },
            {
                "node": {
                    "id": "Class:rap:RemoteBizIdService",
                    "type": "Class",
                    "name": "RemoteBizIdService",
                    "project": "rap",
                    "file_path": "rap/RemoteBizIdService.java",
                    "line": 24,
                },
                "score": 2.5,
                "sources": ["graph_exact", "sparse_fts"],
            },
            {
                "node": {
                    "id": "FeignClient:rap:RemoteBizIdService",
                    "type": "FeignClient",
                    "name": "RemoteBizIdService",
                    "project": "rap",
                    "file_path": "rap/RemoteBizIdService.java",
                    "line": 24,
                },
                "score": 1.3,
                "sources": ["graph_exact", "sparse_fts", "sparse_bm25"],
            },
            {
                "node": {
                    "id": "Method:rap:RemoteBizIdService:getId",
                    "type": "Method",
                    "name": "RemoteBizIdService.getId",
                    "project": "rap",
                    "file_path": "rap/RemoteBizIdService.java",
                    "line": 32,
                },
                "score": 1.1,
                "sources": ["graph_exact", "sparse_fts", "sparse_bm25"],
            },
        ]

        reranked = _rerank_symbol_like_matches(items, "RemoteBizIdService")
        ordered_types = [item["node"]["type"] for item in reranked]
        assert ordered_types[:4] == ["Class", "FeignClient", "Method", "Field"]

    def test_memory_symbol_uses_wider_internal_recall_before_final_limit(self, monkeypatch, tmp_path):
        from memory_center.core.orchestrator import query as query_mod

        ws = tmp_path / ".memory-center" / "workspace.yaml"
        ws.parent.mkdir(parents=True, exist_ok=True)
        ws.write_text("workspace: test\nroot: /tmp/test\nservices: []\n", encoding="utf-8")

        called = {}

        def fake_hybrid(workspace_file, name, limit, node_types=None, project=""):
            called["limit"] = limit
            return {
                "query": name,
                "matches": [
                    {"node": {"id": "Class:rap:RemoteBizIdService", "type": "Class", "name": "RemoteBizIdService", "project": "rap", "file_path": "rap/RemoteBizIdService.java", "line": 24}, "score": 9.0, "sources": ["graph_exact"]},
                    {"node": {"id": "Field:other:A:remoteBizIdService", "type": "Field", "name": "A.remoteBizIdService", "project": "other", "file_path": "other/A.java", "line": 10}, "score": 8.0, "sources": ["graph_exact"]},
                    {"node": {"id": "Field:other:B:remoteBizIdService", "type": "Field", "name": "B.remoteBizIdService", "project": "other", "file_path": "other/B.java", "line": 11}, "score": 7.0, "sources": ["graph_exact"]},
                    {"node": {"id": "Field:other:C:remoteBizIdService", "type": "Field", "name": "C.remoteBizIdService", "project": "other", "file_path": "other/C.java", "line": 12}, "score": 6.0, "sources": ["graph_exact"]},
                    {"node": {"id": "Field:other:D:remoteBizIdService", "type": "Field", "name": "D.remoteBizIdService", "project": "other", "file_path": "other/D.java", "line": 13}, "score": 5.0, "sources": ["graph_exact"]},
                    {"node": {"id": "FeignClient:rap:RemoteBizIdService", "type": "FeignClient", "name": "RemoteBizIdService", "project": "rap", "file_path": "rap/RemoteBizIdService.java", "line": 24}, "score": 4.0, "sources": ["graph_exact"]},
                ],
                "retrieval_summary": {},
            }

        monkeypatch.setattr(query_mod, "memory_query_hybrid", fake_hybrid)
        result = query_mod.memory_symbol(str(ws), "RemoteBizIdService", limit=5)

        assert called["limit"] > 5
        assert len(result["matches"]) == 5
        assert [item["node"]["type"] for item in result["matches"][:2]] == ["Class", "FeignClient"]

    def test_symbol_display_dedupes_feign_method_and_method_by_same_name(self):
        from memory_center.core.orchestrator.query import _dedupe_symbol_display_matches

        items = [
            {
                "node": {
                    "id": "FeignMethod:rap:RemoteBizIdService:getId",
                    "type": "FeignMethod",
                    "name": "RemoteBizIdService.getId",
                    "project": "rap",
                    "file_path": "rap/RemoteBizIdService.java",
                    "line": 32,
                },
                "score": 1.3,
                "sources": ["graph_exact"],
            },
            {
                "node": {
                    "id": "Method:rap:RemoteBizIdService:getId",
                    "type": "Method",
                    "name": "RemoteBizIdService.getId",
                    "project": "rap",
                    "file_path": "rap/RemoteBizIdService.java",
                    "line": 32,
                },
                "score": 1.2,
                "sources": ["graph_exact"],
            },
            {
                "node": {
                    "id": "Method:rap:RemoteBizIdService:getIdByName",
                    "type": "Method",
                    "name": "RemoteBizIdService.getIdByName",
                    "project": "rap",
                    "file_path": "rap/RemoteBizIdService.java",
                    "line": 43,
                },
                "score": 1.1,
                "sources": ["graph_exact"],
            },
        ]

        deduped = _dedupe_symbol_display_matches(items)
        assert len(deduped) == 2
        assert deduped[0]["node"]["type"] == "FeignMethod"
        assert deduped[0]["node"]["name"] == "RemoteBizIdService.getId"
        assert deduped[1]["node"]["name"] == "RemoteBizIdService.getIdByName"

    def test_lookup_payload_dedupes_feign_method_and_method_entrypoints(self):
        from memory_center.core.orchestrator.query import _build_lookup_payload

        payload = _build_lookup_payload(
            {
                "query": "RemoteBizIdService",
                "matches": [
                    {
                        "node": {
                            "id": "FeignMethod:rap:RemoteBizIdService:getId",
                            "type": "FeignMethod",
                            "name": "RemoteBizIdService.getId",
                            "project": "rap",
                            "file_path": "rap/RemoteBizIdService.java",
                            "line": 32,
                        },
                        "sources": ["graph_exact"],
                        "score": 1.3,
                    },
                    {
                        "node": {
                            "id": "Method:rap:RemoteBizIdService:getId",
                            "type": "Method",
                            "name": "RemoteBizIdService.getId",
                            "project": "rap",
                            "file_path": "rap/RemoteBizIdService.java",
                            "line": 32,
                        },
                        "sources": ["graph_exact"],
                        "score": 1.2,
                    },
                    {
                        "node": {
                            "id": "Class:rap:RemoteBizIdService",
                            "type": "Class",
                            "name": "RemoteBizIdService",
                            "project": "rap",
                            "file_path": "rap/RemoteBizIdService.java",
                            "line": 24,
                        },
                        "sources": ["graph_exact"],
                        "score": 2.0,
                    },
                ],
            },
            limit=5,
        )

        entrypoints = payload["entrypoints"]
        assert len(entrypoints) == 2
        assert [item["node"]["type"] for item in entrypoints] == ["FeignMethod", "Class"]

    def test_filter_call_edges_drops_redundant_import_when_stronger_edge_exists(self):
        from memory_center.core.orchestrator.shared import _filter_call_edges

        edges = [
            {
                "type": "INJECTS_BEAN",
                "confidence": 0.82,
                "depth": 1,
                "source": {
                    "name": "MediaReportQuestionServiceImpl",
                    "project": "ucap-newmedia-back",
                    "file_path": "a/MediaReportQuestionServiceImpl.java",
                },
                "target": {
                    "name": "RemoteBizIdService",
                    "project": "ucap-rap-id-app",
                    "file_path": "b/RemoteBizIdService.java",
                },
            },
            {
                "type": "IMPORTS",
                "confidence": 0.55,
                "depth": 2,
                "source": {
                    "name": "MediaReportQuestionServiceImpl.java",
                    "project": "ucap-newmedia-back",
                    "file_path": "a/MediaReportQuestionServiceImpl.java",
                },
                "target": {
                    "name": "RemoteBizIdService.java",
                    "project": "ucap-rap-id-app",
                    "file_path": "b/RemoteBizIdService.java",
                },
            },
        ]

        filtered = _filter_call_edges(edges, direction="upstream")
        assert len(filtered) == 1
        assert filtered[0]["type"] == "INJECTS_BEAN"

    def test_filter_call_edges_prefers_stronger_edge_type_before_weaker_import(self):
        from memory_center.core.orchestrator.shared import _filter_call_edges

        edges = [
            {
                "type": "IMPORTS",
                "confidence": 0.99,
                "depth": 1,
                "source": {"name": "A.java", "project": "p1", "file_path": "a/A.java", "line": 0},
                "target": {"name": "B.java", "project": "p2", "file_path": "b/B.java", "line": 0},
            },
            {
                "type": "INJECTS_BEAN",
                "confidence": 0.82,
                "depth": 1,
                "source": {"name": "AService", "project": "p1", "file_path": "a/A.java", "line": 18},
                "target": {"name": "BService", "project": "p2", "file_path": "b/B.java", "line": 24},
            },
        ]

        filtered = _filter_call_edges(edges, direction="upstream")
        assert filtered[0]["type"] == "INJECTS_BEAN"
        assert all(item["type"] != "IMPORTS" for item in filtered)

    def test_filter_call_edges_keeps_imports_only_as_fallback(self):
        from memory_center.core.orchestrator.shared import _filter_call_edges

        edges = [
            {
                "type": "IMPORTS",
                "confidence": 0.55,
                "depth": 1,
                "source": {"name": "A.java", "project": "p1", "file_path": "a/A.java", "line": 0},
                "target": {"name": "B.java", "project": "p2", "file_path": "b/B.java", "line": 0},
            },
            {
                "type": "IMPORTS",
                "confidence": 0.52,
                "depth": 2,
                "source": {"name": "C.java", "project": "p3", "file_path": "c/C.java", "line": 0},
                "target": {"name": "B.java", "project": "p2", "file_path": "b/B.java", "line": 0},
            },
        ]

        filtered = _filter_call_edges(edges, direction="upstream")
        assert len(filtered) == 1
        assert all(item["type"] == "IMPORTS" for item in filtered)

    def test_row_edge_exposes_source_and_target_line(self):
        from memory_center.core.storage.graph import _row_edge

        class FakeRow(dict):
            def __getitem__(self, key):
                return dict.__getitem__(self, key)

        row = FakeRow(
            id="e1",
            type="CALLS_METHOD",
            source_id="s1",
            target_id="t1",
            confidence=0.9,
            metadata_json="{}",
            source_type="Class",
            source_name="FooService",
            source_project="demo",
            source_file="demo/FooService.java",
            source_line=18,
            target_type="Method",
            target_name="BarService.run",
            target_project="demo",
            target_file="demo/BarService.java",
            target_line=42,
        )

        edge = _row_edge(row)
        assert edge["source"]["line"] == 18
        assert edge["target"]["line"] == 42

    def test_row_edge_falls_back_to_source_evidence_line_when_node_line_missing(self):
        from memory_center.core.storage.graph import _row_edge

        class FakeRow(dict):
            def __getitem__(self, key):
                return dict.__getitem__(self, key)

        row = FakeRow(
            id="e2",
            type="INJECTS_BEAN",
            source_id="s2",
            target_id="t2",
            confidence=0.82,
            metadata_json='{"evidence": {"field_name": "remoteBizIdService", "line": 55}}',
            source_type="Class",
            source_name="MediaReportQuestionServiceImpl",
            source_project="demo",
            source_file="demo/MediaReportQuestionServiceImpl.java",
            source_line=0,
            target_type="Class",
            target_name="RemoteBizIdService",
            target_project="demo",
            target_file="demo/RemoteBizIdService.java",
            target_line=24,
        )

        edge = _row_edge(row)
        assert edge["source"]["line"] == 55
        assert edge["target"]["line"] == 24

    def test_summarize_chain_edges_builds_compact_debug_lines(self):
        from memory_center.core.orchestrator.query import _summarize_chain_edges

        summary = _summarize_chain_edges(
            [
                {
                    "type": "INJECTS_BEAN",
                    "depth": 1,
                    "source": {"name": "MediaReportQuestionServiceImpl", "line": 58, "project": "a"},
                    "target": {"name": "RemoteBizIdService", "line": 24, "project": "b"},
                },
                {
                    "type": "CALLS_SERVICE",
                    "depth": 2,
                    "source": {"name": "RemoteBizIdService", "line": 24, "project": "b"},
                    "target": {"name": "ucap-rap-id-app", "line": 0, "project": "b"},
                },
            ]
        )

        assert summary["total_edges"] == 2
        assert summary["depth_reached"] == 2
        assert summary["type_counts"]["INJECTS_BEAN"] == 1
        assert summary["items"][0]["text"] == "MediaReportQuestionServiceImpl:58 --INJECTS_BEAN--> RemoteBizIdService:24"
        assert summary["items"][1]["text"] == "RemoteBizIdService:24 --CALLS_SERVICE--> ucap-rap-id-app"

    def test_parser_benchmark_returns_diagnostics_when_tree_sitter_unavailable(self, demo_workspace, monkeypatch):
        from memory_center.core.indexing import benchmark as benchmark_mod

        class FakeUnavailableParser:
            name = "tree-sitter"
            available = False

            def parse(self, text, file_path):
                raise AssertionError("should not parse when unavailable")

        monkeypatch.setattr(benchmark_mod, "TreeSitterJavaParser", FakeUnavailableParser)
        result = benchmark_mod.benchmark_java_parsers(str(demo_workspace), limit=20)
        assert result["files_scanned"] >= 1
        assert result["tree_sitter"]["status"] == "unavailable"
        assert result["quality"] == "unknown"

    def test_parser_benchmark_detects_lagging_fields(self, demo_workspace, monkeypatch):
        from memory_center.core.indexing import benchmark as benchmark_mod
        from memory_center.core.indexing.base import JavaParseResult

        class FakeRegexParser:
            name = "regex"

            def parse(self, text, file_path):
                return JavaParseResult(
                    package="com.example",
                    classes=["Demo"],
                    methods=["run"],
                    annotations=["Service"],
                    bean_injections=[{"field_name": "client", "type": "Client"}],
                )

        class FakeTreeParser:
            name = "tree-sitter"
            available = True

            def parse(self, text, file_path):
                return JavaParseResult(
                    package="com.example",
                    classes=["Demo"],
                    methods=[],
                    annotations=["Service"],
                    bean_injections=[],
                )

        monkeypatch.setattr(benchmark_mod, "RegexJavaParser", FakeRegexParser)
        monkeypatch.setattr(benchmark_mod, "TreeSitterJavaParser", FakeTreeParser)
        result = benchmark_mod.benchmark_java_parsers(str(demo_workspace), limit=5, max_findings=10)
        assert result["tree_sitter"]["status"] == "active"
        assert result["regressions"]
        assert any(item["field"] == "methods" for item in result["regressions"])
        assert result["score"] < 100

    def test_parser_benchmark_field_types_treats_more_precise_tree_types_as_non_regression(self, demo_workspace, monkeypatch):
        from memory_center.core.indexing import benchmark as benchmark_mod
        from memory_center.core.indexing.base import JavaParseResult

        class FakeRegexParser:
            name = "regex"

            def parse(self, text, file_path):
                return JavaParseResult(
                    field_types={
                        "jobLRUMap": "String>>",
                        "LOGIN_IDENTITY_KEY": "XXL_JOB_LOGIN_IDENTITY",
                    },
                )

        class FakeTreeParser:
            name = "tree-sitter"
            available = True

            def parse(self, text, file_path):
                return JavaParseResult(
                    field_types={
                        "jobLRUMap": "ConcurrentMap<Integer, LinkedHashMap<String, String>>",
                        "LOGIN_IDENTITY_KEY": "String",
                    },
                )

        monkeypatch.setattr(benchmark_mod, "RegexJavaParser", FakeRegexParser)
        monkeypatch.setattr(benchmark_mod, "TreeSitterJavaParser", FakeTreeParser)
        result = benchmark_mod.benchmark_java_parsers(str(demo_workspace), limit=5, max_findings=10)
        field_stats = result["summary"]["field_stats"]["field_types"]
        assert field_stats["lagging_files"] == 0
        assert not any(item["field"] == "field_types" for item in result["regressions"])
        assert result["score"] == 100

    def test_parser_benchmark_field_types_treats_string_literals_as_string_type(self, demo_workspace, monkeypatch):
        from memory_center.core.indexing import benchmark as benchmark_mod
        from memory_center.core.indexing.base import JavaParseResult

        class FakeRegexParser:
            name = "regex"

            def parse(self, text, file_path):
                return JavaParseResult(field_types={"COOKIE_PATH": "/", "COMMA": ",", "FALLBACK_USER_ID": "0"})

        class FakeTreeParser:
            name = "tree-sitter"
            available = True

            def parse(self, text, file_path):
                return JavaParseResult(field_types={"COOKIE_PATH": "String", "COMMA": "String", "FALLBACK_USER_ID": "int"})

        monkeypatch.setattr(benchmark_mod, "RegexJavaParser", FakeRegexParser)
        monkeypatch.setattr(benchmark_mod, "TreeSitterJavaParser", FakeTreeParser)
        result = benchmark_mod.benchmark_java_parsers(str(demo_workspace), limit=5, max_findings=10)
        assert result["summary"]["field_stats"]["field_types"]["lagging_files"] == 0
        assert not result["regressions"]

    def test_parser_benchmark_field_types_uses_constant_name_context_for_string_values(self, demo_workspace, monkeypatch):
        from memory_center.core.indexing import benchmark as benchmark_mod
        from memory_center.core.indexing.base import JavaParseResult

        class FakeRegexParser:
            name = "regex"

            def parse(self, text, file_path):
                return JavaParseResult(field_types={"BASIC_": "Basic", "NO_METRICS": "No metrics"})

        class FakeTreeParser:
            name = "tree-sitter"
            available = True

            def parse(self, text, file_path):
                return JavaParseResult(field_types={"BASIC_": "String", "NO_METRICS": "String"})

        monkeypatch.setattr(benchmark_mod, "RegexJavaParser", FakeRegexParser)
        monkeypatch.setattr(benchmark_mod, "TreeSitterJavaParser", FakeTreeParser)
        result = benchmark_mod.benchmark_java_parsers(str(demo_workspace), limit=5, max_findings=10)
        assert result["summary"]["field_stats"]["field_types"]["lagging_files"] == 0
        assert not result["regressions"]

    def test_parser_benchmark_samples_across_services_in_round_robin_order(self, tmp_path, monkeypatch):
        from memory_center.core.indexing import benchmark as benchmark_mod
        from memory_center.core.indexing.base import JavaParseResult

        root = tmp_path / "repo"
        (root / "svc-a").mkdir(parents=True)
        (root / "svc-b").mkdir(parents=True)
        (root / "svc-a" / "A1.java").write_text("class A1 {}", encoding="utf-8")
        (root / "svc-a" / "A2.java").write_text("class A2 {}", encoding="utf-8")
        (root / "svc-b" / "B1.java").write_text("class B1 {}", encoding="utf-8")
        (root / "svc-b" / "B2.java").write_text("class B2 {}", encoding="utf-8")

        workspace = root / ".memory-center" / "workspace.yaml"
        workspace.parent.mkdir(parents=True)
        workspace.write_text(
            yaml.safe_dump(
                {
                    "workspace": "sample",
                    "root": str(root),
                    "services": [
                        {"name": "svc-a", "path": "svc-a"},
                        {"name": "svc-b", "path": "svc-b"},
                    ],
                },
                sort_keys=False,
                allow_unicode=True,
            ),
            encoding="utf-8",
        )

        class FakeRegexParser:
            name = "regex"

            def parse(self, text, file_path):
                return JavaParseResult(classes=[Path(file_path).stem])

        class FakeTreeParser(FakeRegexParser):
            name = "tree-sitter"
            available = True

        monkeypatch.setattr(benchmark_mod, "RegexJavaParser", FakeRegexParser)
        monkeypatch.setattr(benchmark_mod, "TreeSitterJavaParser", FakeTreeParser)
        result = benchmark_mod.benchmark_java_parsers(str(workspace), limit=2, max_findings=10)
        assert result["files_scanned"] == 2
        assert sorted(result["service_coverage"]["sampled_services"]) == ["svc-a", "svc-b"]
        assert result["service_coverage"]["sampled_file_counts"] == {"svc-a": 1, "svc-b": 1}

    def test_parser_benchmark_reports_duplicate_and_nested_service_roots(self, tmp_path, monkeypatch):
        from memory_center.core.indexing import benchmark as benchmark_mod
        from memory_center.core.indexing.base import JavaParseResult

        root = tmp_path / "repo"
        (root / "parent" / "child").mkdir(parents=True)
        (root / "parent" / "Parent.java").write_text("class Parent {}", encoding="utf-8")
        (root / "parent" / "child" / "Child.java").write_text("class Child {}", encoding="utf-8")

        workspace = root / ".memory-center" / "workspace.yaml"
        workspace.parent.mkdir(parents=True)
        workspace.write_text(
            yaml.safe_dump(
                {
                    "workspace": "shape",
                    "root": str(root),
                    "services": [
                        {"name": "parent", "path": "parent"},
                        {"name": "parent-alias", "path": "parent"},
                        {"name": "child", "path": "parent/child"},
                    ],
                },
                sort_keys=False,
                allow_unicode=True,
            ),
            encoding="utf-8",
        )

        class FakeRegexParser:
            name = "regex"

            def parse(self, text, file_path):
                return JavaParseResult(classes=[Path(file_path).stem])

        class FakeTreeParser(FakeRegexParser):
            name = "tree-sitter"
            available = True

        monkeypatch.setattr(benchmark_mod, "RegexJavaParser", FakeRegexParser)
        monkeypatch.setattr(benchmark_mod, "TreeSitterJavaParser", FakeTreeParser)
        result = benchmark_mod.benchmark_java_parsers(str(workspace), limit=10, max_findings=10)
        duplicate_groups = result["workspace_shape"]["duplicate_root_groups"]
        nested_pairs = result["workspace_shape"]["nested_service_pairs"]
        assert any(sorted(group["services"]) == ["parent", "parent-alias"] for group in duplicate_groups)
        assert any(pair["parent_service"] == "parent" and pair["child_service"] == "child" for pair in nested_pairs)
        assert result["service_coverage"]["total_file_counts"]["child"] == 1


# ═════════════════════════════════════════════════════════════════════════════
# E-03: Parallel Indexing with Fault Tolerance
# ═════════════════════════════════════════════════════════════════════════════

class TestE03ParallelIndexing:
    """E-03: Parallel file parsing with fault tolerance."""

    def test_parse_files_parallel_basic(self):
        from memory_center.core.indexing.java_regex_parser import RegexJavaParser
        from memory_center.core.indexing.parallel import parse_files_parallel
        parser = RegexJavaParser()
        # Empty file list should return empty results
        results = parse_files_parallel([], parser.parse)
        assert results == []

    def test_parse_files_parallel_fault_tolerance(self):
        """Malformed files should not crash parallel parsing."""
        import tempfile

        from memory_center.core.indexing.java_regex_parser import RegexJavaParser
        from memory_center.core.indexing.parallel import parse_files_parallel
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
        # Default max_workers raised from 8 to 32 in CBM-inspired evolution
        # plan P0-3 (IO-bound file reads benefit from oversubscription).
        # The lower bound stays at 1 so explicit cap requests still work.
        w = estimate_optimal_workers(100)
        assert 1 <= w <= 32
        w2 = estimate_optimal_workers(1)
        assert w2 >= 1
        # Explicit cap continues to be honoured.
        assert estimate_optimal_workers(100, max_workers=4) <= 4

    def test_walk_project_files_finds_java(self, demo_workspace: Path):
        from memory_center.core.indexing.parallel import walk_project_files
        # demo_workspace is the workspace.yaml path, get parent project root
        project_root = demo_workspace.parent.parent
        java_files, config_files = walk_project_files(project_root)
        assert isinstance(java_files, list)
        assert isinstance(config_files, list)

    def test_walk_project_ignores_agent_worktree_directories(self, tmp_path: Path):
        from memory_center.core.indexing.reindex import walk_project

        root = tmp_path / "repo"
        (root / "src").mkdir(parents=True)
        (root / ".claude" / "worktrees" / "agent").mkdir(parents=True)
        (root / ".codex" / "cache").mkdir(parents=True)
        (root / "src" / "Real.java").write_text("class Real {}", encoding="utf-8")
        (root / ".claude" / "worktrees" / "agent" / "Shadow.java").write_text("class Shadow {}", encoding="utf-8")
        (root / ".codex" / "cache" / "Ghost.java").write_text("class Ghost {}", encoding="utf-8")

        files = [p.relative_to(root).as_posix() for p in walk_project(root)]
        assert "src/Real.java" in files
        assert ".claude/worktrees/agent/Shadow.java" not in files
        assert ".codex/cache/Ghost.java" not in files


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
        from memory_center.core.storage.runtime import RuntimeStore
        db_path = tmp_path / "test.db"
        store = RuntimeStore(str(db_path))
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
        from memory_center.core.indexing.reindex import reindex_workspace
        from memory_center.core.retrieval.inverted import InvertedIndex
        from memory_center.core.storage.runtime import RuntimeStore
        from memory_center.core.storage.workspace import WorkspaceStore
        from memory_center.core.workspace.config import load_workspace_config

        workspace_store = WorkspaceStore(demo_workspace)
        reindex_workspace(load_workspace_config(demo_workspace), workspace_store)

        with RuntimeStore(workspace_store.graph_db_path) as unified:
            assert InvertedIndex(unified).stats()["doc_count"] > 0


# ═════════════════════════════════════════════════════════════════════════════
# E-07: Native Vector Retrieval
# ═════════════════════════════════════════════════════════════════════════════

class TestE07VectorRetrieval:
    """E-07: Vector index with sqlite-vec / persistent ANN."""

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

    def test_large_index_without_ann_never_uses_python_full_scan(self, unified_store):
        from memory_center.core.storage.vector_index import VectorIndex

        vec = VectorIndex(unified_store, dimension=2)
        vec.upsert_embeddings_batch([(f"node-{index}", [1.0, 0.0]) for index in range(65)])
        stats = vec.stats()
        if not stats["ann_ready"]:
            assert stats["backend"] == "unavailable"
            assert vec.query([1.0, 0.0]) == []

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
        from memory_center.core.indexing.reindex import _sync_retrieval_indexes
        from memory_center.core.storage.runtime import RuntimeStore
        from memory_center.core.storage.vector_index import VectorIndex
        from memory_center.core.storage.workspace import WorkspaceStore

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
        with RuntimeStore(workspace_store.graph_db_path) as unified:
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
        from memory_center.core.storage.runtime import RuntimeStore

        # hybrid_retrieve needs RuntimeStore + workspace_file + query
        from memory_center.core.storage.workspace import WorkspaceStore
        ws = WorkspaceStore(str(demo_workspace))
        with RuntimeStore(ws.graph_db_path) as graph:
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

    def test_merge_retrieval_results_does_not_mutate_input_scores(self):
        """Hybrid fusion normalizes copied hits so callers can reuse raw scores."""
        from memory_center.core.retrieval.hybrid import (
            HybridRetrievalConfig,
            RetrievalResult,
            _merge_retrieval_results,
        )

        hit = RetrievalResult(
            node_id="graph-node",
            node={"id": "graph-node"},
            score=5.0,
            sources=["graph_exact"],
        )
        results = _merge_retrieval_results(
            [hit],
            [],
            [],
            HybridRetrievalConfig(),
            {},
        )
        assert hit.score == 5.0
        assert results[0].score != hit.score

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
        from memory_center.core.storage.runtime import RuntimeStore
        from memory_center.core.storage.vector_index import VectorIndex
        from memory_center.core.storage.workspace import WorkspaceStore
        ws = WorkspaceStore(str(demo_workspace))
        with RuntimeStore(ws.graph_db_path) as unified:
            vec = VectorIndex(unified)
            stats = vec.stats()
            assert "embedding_count" in stats
            assert "dimension" in stats
            assert "backend" in stats
            assert stats["backend"] in ("sqlite-vec", "hnswlib", "exact_small", "unavailable")

    def test_vector_index_upsert_and_query(self, demo_workspace):
        """VectorIndex can upsert and query embeddings."""
        from memory_center.core.storage.runtime import RuntimeStore
        from memory_center.core.storage.vector_index import VectorIndex
        from memory_center.core.storage.workspace import WorkspaceStore
        ws = WorkspaceStore(str(demo_workspace))
        with RuntimeStore(ws.graph_db_path) as unified:
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
        from memory_center.core.storage.runtime import RuntimeStore
        from memory_center.core.storage.vector_index import VectorIndex
        from memory_center.core.storage.workspace import WorkspaceStore
        ws = WorkspaceStore(str(demo_workspace))
        with RuntimeStore(ws.graph_db_path) as unified:
            vec = VectorIndex(unified, dimension=4)
            with pytest.raises(ValueError):
                vec.upsert_embedding("test", [1.0, 0.0])  # wrong dimension
            with pytest.raises(ValueError):
                vec.query([1.0, 0.0])  # wrong dimension

    def test_vector_index_delete(self, demo_workspace):
        """VectorIndex.delete_embedding removes embeddings."""
        from memory_center.core.storage.runtime import RuntimeStore
        from memory_center.core.storage.vector_index import VectorIndex
        from memory_center.core.storage.workspace import WorkspaceStore
        ws = WorkspaceStore(str(demo_workspace))
        with RuntimeStore(ws.graph_db_path) as unified:
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

            def close(self):
                pass

            def node_by_id(self, node_id):
                return {"id": node_id, "type": "Class", "name": "DemoNode", "project": "demo"}

        diagnostics = {}
        with (
            patch("memory_center.core.storage.vector_index.VectorIndex", FakeVectorIndex),
            patch("memory_center.core.storage.runtime.RuntimeStore", FakeGraph),
            patch("memory_center.core.retrieval.semantic.semantic_index_stats", return_value={"model": None, "requested_model": None}),
            patch("memory_center.core.retrieval.semantic._load_sentence_transformer_model", return_value=FakeModel()),
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
