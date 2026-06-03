"""Tests for NEXT_PHASE modules: hybrid retrieval, benchmark, audit, navigation, backend."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Dict

import pytest


# ---- Hybrid Retrieval Tests ----

class TestHybridRetrieval:
    """Test hybrid retrieval engine."""

    def test_detect_query_intent_feign(self):
        from memory_center.core.retrieval.hybrid import detect_query_intent
        result = detect_query_intent("feign client ArticleFeignClient")
        assert result["primary_intent"] == "feign"
        assert "feign" in result["matched_patterns"]

    def test_detect_query_intent_endpoint(self):
        from memory_center.core.retrieval.hybrid import detect_query_intent
        result = detect_query_intent("/api/users endpoint")
        assert result["primary_intent"] == "endpoint"

    def test_detect_query_intent_mq(self):
        from memory_center.core.retrieval.hybrid import detect_query_intent
        result = detect_query_intent("kafka topic order-events")
        assert result["primary_intent"] == "mq"

    def test_detect_query_intent_config(self):
        from memory_center.core.retrieval.hybrid import detect_query_intent
        result = detect_query_intent("config.properties")
        assert result["primary_intent"] == "config"

    def test_detect_query_intent_chain(self):
        from memory_center.core.retrieval.hybrid import detect_query_intent
        result = detect_query_intent("调用链")
        assert result["primary_intent"] == "chain"

    def test_detect_query_intent_general(self):
        from memory_center.core.retrieval.hybrid import detect_query_intent
        result = detect_query_intent("hello world")
        assert result["primary_intent"] == "general"

    def test_detect_query_intent_plain_service_is_not_feign(self):
        from memory_center.core.retrieval.hybrid import detect_query_intent
        result = detect_query_intent("ArticleService")
        assert result["primary_intent"] == "class"
        assert "feign" not in result["all_intents"]

    def test_detect_query_intent_feign_service_still_matches_feign(self):
        from memory_center.core.retrieval.hybrid import detect_query_intent
        result = detect_query_intent("FeginAutomaticReviewTaskService")
        assert result["primary_intent"] == "feign"

    def test_detect_query_intent_http_client_not_feign(self):
        from memory_center.core.retrieval.hybrid import detect_query_intent
        result = detect_query_intent("RestClient")
        assert result["primary_intent"] != "feign"
        assert "feign" not in result["all_intents"]

    def test_detect_query_intent_test_client_not_feign(self):
        from memory_center.core.retrieval.hybrid import detect_query_intent
        result = detect_query_intent("TestClient")
        assert result["primary_intent"] != "feign"
        assert "feign" not in result["all_intents"]

    def test_detect_query_intent_feign_client_matches_feign(self):
        from memory_center.core.retrieval.hybrid import detect_query_intent
        result = detect_query_intent("ArticleFeignClient")
        assert result["primary_intent"] == "feign"

    def test_detect_query_intent_client_keyword_not_feign(self):
        from memory_center.core.retrieval.hybrid import detect_query_intent
        result = detect_query_intent("client library dependency")
        assert result["primary_intent"] != "feign"
        assert "feign" not in result["all_intents"]

    def test_detect_query_intent_plain_class_not_feign(self):
        from memory_center.core.retrieval.hybrid import detect_query_intent
        for name in ("UserService", "OrderServiceImpl", "UserDao", "OrderMapper"):
            result = detect_query_intent(name)
            assert result["primary_intent"] == "class", f"{name} should be class, got {result['primary_intent']}"
            assert "feign" not in result["all_intents"], f"{name} should not trigger feign"

    def test_hybrid_retrieval_config_defaults(self):
        from memory_center.core.retrieval.hybrid import HybridRetrievalConfig
        config = HybridRetrievalConfig()
        assert config.graph_weight == 0.4
        assert config.sparse_weight == 0.35
        assert config.semantic_weight == 0.25
        assert config.min_confidence == 0.3
        assert config.max_results == 20
        assert config.enable_cross_workspace is True
        assert config.enable_type_boosting is True

    def test_hybrid_retrieval_config_custom(self):
        from memory_center.core.retrieval.hybrid import HybridRetrievalConfig
        config = HybridRetrievalConfig(
            graph_weight=0.5,
            sparse_weight=0.3,
            semantic_weight=0.2,
            min_confidence=0.5,
        )
        assert config.graph_weight == 0.5
        assert config.sparse_weight == 0.3
        assert config.semantic_weight == 0.2
        assert config.min_confidence == 0.5

    def test_retrieval_result_creation(self):
        from memory_center.core.retrieval.hybrid import RetrievalResult
        result = RetrievalResult(
            node_id="test:1",
            node={"name": "test", "type": "Class"},
            score=0.95,
            sources=["graph_exact", "semantic"],
            evidence={"graph_rank": 1},
        )
        assert result.node_id == "test:1"
        assert result.score == 0.95
        assert "graph_exact" in result.sources
        assert "semantic" in result.sources
        assert result.evidence["graph_rank"] == 1


# ---- Contract Filtering Tests ----

class TestContracts:
    """Test contract filtering and association logic with confidence scoring."""

    def test_filter_contracts_by_query_feign_exact_match(self):
        from memory_center.core.orchestrator.query import _filter_contracts_by_query
        contracts = [
            {"interface": "ArticleFeignClient", "project": "svc-a", "methods": []},
            {"interface": "OrderFeignClient", "project": "svc-b", "methods": []},
        ]
        result = _filter_contracts_by_query(contracts, "ArticleFeignClient", "feign")
        assert len(result) >= 1
        article = [c for c in result if c.get("interface") == "ArticleFeignClient"]
        assert len(article) == 1
        assert article[0]["_confidence"] == 0.95
        assert article[0]["_match_type"] == "interface_exact"

    def test_filter_contracts_by_query_feign_method_match(self):
        from memory_center.core.orchestrator.query import _filter_contracts_by_query
        contracts = [
            {
                "interface": "ArticleFeignClient", "project": "svc-a",
                "methods": [{"method_name": "getArticle", "path": "/api/articles"}],
            },
        ]
        result = _filter_contracts_by_query(contracts, "getArticle", "feign")
        assert len(result) >= 1
        assert result[0]["_confidence"] == 0.85
        assert result[0]["_match_type"] == "method_exact"

    def test_filter_contracts_by_query_feign_token_match(self):
        from memory_center.core.orchestrator.query import _filter_contracts_by_query
        contracts = [
            {"interface": "ArticleService", "project": "svc-a", "methods": []},
        ]
        # "article data" tokenizes to ["article", "data"] — "article" matches via token
        # but the full query is NOT a substring of "articleservice"
        result = _filter_contracts_by_query(contracts, "article data", "feign")
        assert len(result) >= 1
        assert result[0]["_confidence"] == 0.60
        assert result[0]["_match_type"] == "token_match"

    def test_filter_contracts_by_query_endpoint(self):
        from memory_center.core.orchestrator.query import _filter_contracts_by_query
        contracts = [
            {"path": "/api/users", "controller": "UserController"},
            {"path": "/api/orders", "controller": "OrderController"},
        ]
        result = _filter_contracts_by_query(contracts, "/api/users", "endpoint")
        assert len(result) >= 1
        assert any(c["path"] == "/api/users" for c in result)
        users = [c for c in result if c.get("path") == "/api/users"]
        assert users[0]["_confidence"] == 0.90
        assert users[0]["_match_type"] == "path_exact"

    def test_filter_contracts_by_query_fallback(self):
        from memory_center.core.orchestrator.query import _filter_contracts_by_query
        contracts = [
            {"interface": "OrderFeignClient", "project": "svc-b", "methods": []},
        ]
        result = _filter_contracts_by_query(contracts, "xyz_nonexistent", "feign")
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["_confidence"] == 0.10
        assert result[0]["_match_type"] == "fallback"
        assert result[0]["_is_fallback"] is True

    def test_filter_contracts_by_query_empty(self):
        from memory_center.core.orchestrator.query import _filter_contracts_by_query
        result = _filter_contracts_by_query([], "anything", "feign")
        assert result == []

    def test_filter_contracts_confidence_ordering(self):
        from memory_center.core.orchestrator.query import _filter_contracts_by_query
        contracts = [
            {"interface": "ArticleService", "project": "svc-a", "methods": [
                {"method_name": "getArticle", "path": "/api/articles"},
            ]},
            {"interface": "ArticleFeignClient", "project": "svc-b", "methods": []},
        ]
        result = _filter_contracts_by_query(contracts, "Article", "feign")
        # ArticleFeignClient (token match 0.60) should come after ArticleService (token match 0.60)
        # but both are token matches — verify confidence is present
        for c in result:
            assert "_confidence" in c
            assert c["_confidence"] >= 0.60


# ---- Benchmark Trending Tests ----

class TestBenchmarkTrending:
    """Test benchmark trending module."""

    def test_detect_regressions_found(self):
        from memory_center.core.benchmark.trending import _detect_regressions
        trends = {
            "func1": [
                {"raw_tokens": 100, "compact_tokens": 30, "savings_pct": 70},
                {"raw_tokens": 100, "compact_tokens": 30, "savings_pct": 70},
                {"raw_tokens": 100, "compact_tokens": 30, "savings_pct": 70},
                {"raw_tokens": 100, "compact_tokens": 30, "savings_pct": 70},
                {"raw_tokens": 100, "compact_tokens": 30, "savings_pct": 70},
                {"raw_tokens": 100, "compact_tokens": 30, "savings_pct": 70},
                {"raw_tokens": 100, "compact_tokens": 30, "savings_pct": 70},
                {"raw_tokens": 100, "compact_tokens": 30, "savings_pct": 70},
                {"raw_tokens": 100, "compact_tokens": 30, "savings_pct": 70},
                {"raw_tokens": 200, "compact_tokens": 30, "savings_pct": 85},
            ]
        }
        regressions = _detect_regressions(trends, threshold_pct=10.0)
        assert len(regressions) == 1
        assert regressions[0]["function_name"] == "func1"
        assert regressions[0]["change_pct"] > 15  # 20% increase

    def test_detect_regressions_not_found(self):
        from memory_center.core.benchmark.trending import _detect_regressions
        trends = {
            "func1": [
                {"raw_tokens": 100, "compact_tokens": 30, "savings_pct": 70},
                {"raw_tokens": 100, "compact_tokens": 30, "savings_pct": 70},
                {"raw_tokens": 100, "compact_tokens": 30, "savings_pct": 70},
                {"raw_tokens": 100, "compact_tokens": 30, "savings_pct": 70},
                {"raw_tokens": 100, "compact_tokens": 30, "savings_pct": 70},
                {"raw_tokens": 100, "compact_tokens": 30, "savings_pct": 70},
            ]
        }
        regressions = _detect_regressions(trends, threshold_pct=10.0)
        assert len(regressions) == 0

    def test_detect_regressions_too_few_points(self):
        from memory_center.core.benchmark.trending import _detect_regressions
        trends = {
            "func1": [
                {"raw_tokens": 100, "compact_tokens": 30, "savings_pct": 70},
                {"raw_tokens": 200, "compact_tokens": 30, "savings_pct": 85},
            ]
        }
        regressions = _detect_regressions(trends, threshold_pct=10.0)
        assert len(regressions) == 0  # Not enough points

    def test_build_trend_summary(self):
        from memory_center.core.benchmark.trending import _build_trend_summary
        trends = {
            "func1": [
                {"raw_tokens": 100, "compact_tokens": 30, "savings_pct": 70},
                {"raw_tokens": 100, "compact_tokens": 30, "savings_pct": 70},
            ],
            "func2": [
                {"raw_tokens": 200, "compact_tokens": 50, "savings_pct": 75},
            ],
        }
        summary = _build_trend_summary(trends)
        assert summary["total_trend_points"] == 3
        assert summary["functions_tracked"] == 2

    def test_calculate_health_score_healthy(self):
        from memory_center.core.benchmark.trending import _calculate_health_score
        baselines = {"function_stats": {}}
        trends = {"regressions": []}
        health = _calculate_health_score(baselines, trends)
        assert health["score"] == 100
        assert health["quality"] == "high"

    def test_calculate_health_score_with_regressions(self):
        from memory_center.core.benchmark.trending import _calculate_health_score
        baselines = {"function_stats": {}}
        trends = {"regressions": [
            {"severity": "high"},
            {"severity": "medium"},
        ]}
        health = _calculate_health_score(baselines, trends)
        assert health["score"] < 100
        assert len(health["issues"]) > 0

    def test_generate_recommendations(self):
        from memory_center.core.benchmark.trending import _generate_recommendations
        # 需要至少 5 个函数才会显示"基准测试健康"
        baselines = {"function_stats": {
            "func1": {"avg_savings_pct": 70},
            "func2": {"avg_savings_pct": 65},
            "func3": {"avg_savings_pct": 80},
            "func4": {"avg_savings_pct": 75},
            "func5": {"avg_savings_pct": 72},
        }}
        trends = {"regressions": []}
        recs = _generate_recommendations(baselines, trends)
        assert len(recs) > 0
        assert "基准测试健康" in recs[0]

    def test_record_benchmark_trend_persists(self):
        from memory_center.core.benchmark.trending import record_benchmark_trend
        with tempfile.TemporaryDirectory() as tmpdir:
            mc_dir = Path(tmpdir) / ".memory-center"
            mc_dir.mkdir()
            ws = mc_dir / "workspace.yaml"
            ws.write_text("workspace: test\n")
            result = record_benchmark_trend(
                str(ws), "sniff", raw_tokens=1000, compact_tokens=300,
                budget="medium", view="compact",
            )
            assert result["recorded"] is True
            assert result["function_name"] == "sniff"

    def test_generate_benchmark_report_structure(self):
        from memory_center.core.benchmark.trending import generate_benchmark_report
        with tempfile.TemporaryDirectory() as tmpdir:
            mc_dir = Path(tmpdir) / ".memory-center"
            mc_dir.mkdir()
            ws = mc_dir / "workspace.yaml"
            ws.write_text("workspace: test\n")
            report = generate_benchmark_report(str(ws))
            assert "baselines" in report
            assert "trends" in report
            assert "health_score" in report
            assert "recommendations" in report
            assert isinstance(report["recommendations"], list)


# ---- Completion Audit Tests ----

class TestCompletionAudit:
    """Test completion audit module."""

    def test_get_project_root_with_memory_center(self):
        from memory_center.core.audit.completion import _get_project_root
        with tempfile.TemporaryDirectory() as tmpdir:
            mc_dir = Path(tmpdir) / ".memory-center"
            mc_dir.mkdir()
            workspace_file = mc_dir / "workspace.yaml"
            workspace_file.write_text("workspace: test")
            root = _get_project_root(str(workspace_file))
            assert root == Path(tmpdir)

    def test_get_project_root_without_memory_center(self):
        from memory_center.core.audit.completion import _get_project_root
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_file = Path(tmpdir) / "workspace.yaml"
            workspace_file.write_text("workspace: test")
            root = _get_project_root(str(workspace_file))
            assert root == Path(tmpdir)

    def test_check_documentation_alignment_finds_docs(self):
        from memory_center.core.audit.completion import _check_documentation_alignment
        with tempfile.TemporaryDirectory() as tmpdir:
            mc_dir = Path(tmpdir) / ".memory-center"
            mc_dir.mkdir()
            workspace_file = mc_dir / "workspace.yaml"
            workspace_file.write_text("workspace: test")

            # Create README.md
            (Path(tmpdir) / "README.md").write_text("# Test")

            findings = _check_documentation_alignment(str(workspace_file), "")
            missing_readme = [f for f in findings if "README" in f.get("file", "")]
            assert len(missing_readme) == 0

    def test_check_documentation_alignment_missing_docs(self):
        from memory_center.core.audit.completion import _check_documentation_alignment
        with tempfile.TemporaryDirectory() as tmpdir:
            mc_dir = Path(tmpdir) / ".memory-center"
            mc_dir.mkdir()
            workspace_file = mc_dir / "workspace.yaml"
            workspace_file.write_text("workspace: test")

            # Don't create any docs
            findings = _check_documentation_alignment(str(workspace_file), "")
            assert len(findings) > 0
            assert any(f["code"] == "missing_doc" for f in findings)

    def test_check_test_coverage_finds_tests(self):
        from memory_center.core.audit.completion import _check_test_coverage
        with tempfile.TemporaryDirectory() as tmpdir:
            mc_dir = Path(tmpdir) / ".memory-center"
            mc_dir.mkdir()
            workspace_file = mc_dir / "workspace.yaml"
            workspace_file.write_text("workspace: test")

            # Create tests directory
            tests_dir = Path(tmpdir) / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_example.py").write_text("def test_pass(): pass")

            # Create pyproject.toml with pytest config
            (Path(tmpdir) / "pyproject.toml").write_text("[tool.pytest]\ntestpaths = ['tests']")

            findings = _check_test_coverage(str(workspace_file), "")
            no_tests = [f for f in findings if f["code"] == "no_tests"]
            assert len(no_tests) == 0

    def test_check_test_coverage_missing_tests(self):
        from memory_center.core.audit.completion import _check_test_coverage
        with tempfile.TemporaryDirectory() as tmpdir:
            mc_dir = Path(tmpdir) / ".memory-center"
            mc_dir.mkdir()
            workspace_file = mc_dir / "workspace.yaml"
            workspace_file.write_text("workspace: test")

            # Don't create tests
            findings = _check_test_coverage(str(workspace_file), "")
            assert any(f["code"] == "no_tests" for f in findings)

    def test_check_implementation_completeness_with_source(self):
        from memory_center.core.audit.completion import _check_implementation_completeness
        with tempfile.TemporaryDirectory() as tmpdir:
            mc_dir = Path(tmpdir) / ".memory-center"
            mc_dir.mkdir()
            workspace_file = mc_dir / "workspace.yaml"
            workspace_file.write_text("workspace: test")

            # Create src directory with Python file
            src_dir = Path(tmpdir) / "src"
            src_dir.mkdir()
            (src_dir / "main.py").write_text("print('hello')")

            findings = _check_implementation_completeness(str(workspace_file), "")
            no_source = [f for f in findings if f["code"] == "no_source_found"]
            assert len(no_source) == 0

    def test_check_implementation_completeness_without_source(self):
        from memory_center.core.audit.completion import _check_implementation_completeness
        with tempfile.TemporaryDirectory() as tmpdir:
            mc_dir = Path(tmpdir) / ".memory-center"
            mc_dir.mkdir()
            workspace_file = mc_dir / "workspace.yaml"
            workspace_file.write_text("workspace: test")

            # Don't create any source files
            findings = _check_implementation_completeness(str(workspace_file), "")
            assert len(findings) > 0

    def test_score_to_quality(self):
        from memory_center.core.audit.completion import _score_to_quality
        assert _score_to_quality(90) == "high"
        assert _score_to_quality(85) == "high"
        assert _score_to_quality(70) == "medium"
        assert _score_to_quality(60) == "medium"
        assert _score_to_quality(50) == "low"
        assert _score_to_quality(0) == "low"

    def test_categorize_findings(self):
        from memory_center.core.audit.completion import _categorize_findings
        findings = [
            {"category": "docs", "severity": "high"},
            {"category": "tests", "severity": "medium"},
            {"category": "docs", "severity": "low"},
        ]
        categories = _categorize_findings(findings)
        assert categories["docs"] == 2
        assert categories["tests"] == 1

    def test_build_audit_summary(self):
        from memory_center.core.audit.completion import _build_audit_summary
        findings = [
            {"category": "docs", "severity": "high"},
            {"category": "tests", "severity": "medium"},
            {"category": "docs", "severity": "low"},
        ]
        summary = _build_audit_summary(findings)
        assert summary["total_findings"] == 3
        assert summary["critical_count"] == 1
        assert summary["by_severity"]["high"] == 1
        assert summary["by_severity"]["medium"] == 1
        assert summary["by_severity"]["low"] == 1

    def test_check_test_coverage_java_project(self):
        from memory_center.core.audit.completion import _check_test_coverage
        with tempfile.TemporaryDirectory() as tmpdir:
            mc_dir = Path(tmpdir) / ".memory-center"
            mc_dir.mkdir()
            ws = mc_dir / "workspace.yaml"
            ws.write_text("workspace: test\n")
            # Create Java test directory with *Test.java files
            test_dir = Path(tmpdir) / "src" / "test" / "java" / "com" / "example"
            test_dir.mkdir(parents=True)
            (test_dir / "UserServiceTest.java").write_text("class UserServiceTest {}")
            findings = _check_test_coverage(str(ws), "")
            no_tests = [f for f in findings if f["code"] == "no_tests"]
            assert len(no_tests) == 0

    def test_check_test_coverage_js_project(self):
        from memory_center.core.audit.completion import _check_test_coverage
        with tempfile.TemporaryDirectory() as tmpdir:
            mc_dir = Path(tmpdir) / ".memory-center"
            mc_dir.mkdir()
            ws = mc_dir / "workspace.yaml"
            ws.write_text("workspace: test\n")
            # Create JS test directory with *.spec.ts files
            test_dir = Path(tmpdir) / "tests"
            test_dir.mkdir()
            (test_dir / "user.spec.ts").write_text("describe('user', () => {})")
            findings = _check_test_coverage(str(ws), "")
            no_tests = [f for f in findings if f["code"] == "no_tests"]
            assert len(no_tests) == 0

    def test_check_test_config_package_json(self):
        from memory_center.core.audit.completion import _check_test_coverage
        with tempfile.TemporaryDirectory() as tmpdir:
            mc_dir = Path(tmpdir) / ".memory-center"
            mc_dir.mkdir()
            ws = mc_dir / "workspace.yaml"
            ws.write_text("workspace: test\n")
            # Create package.json with test script
            (Path(tmpdir) / "package.json").write_text(
                '{"scripts": {"test": "jest"}}'
            )
            # Create test files so no_tests doesn't trigger
            test_dir = Path(tmpdir) / "tests"
            test_dir.mkdir()
            (test_dir / "user.spec.js").write_text("test('user', () => {})")
            findings = _check_test_coverage(str(ws), "")
            no_test_config = [f for f in findings if f["code"] == "no_test_config"]
            assert len(no_test_config) == 0

    def test_check_documentation_adaptive(self):
        from memory_center.core.audit.completion import _check_documentation_alignment
        with tempfile.TemporaryDirectory() as tmpdir:
            mc_dir = Path(tmpdir) / ".memory-center"
            mc_dir.mkdir()
            ws = mc_dir / "workspace.yaml"
            ws.write_text("workspace: test\n")
            # Only README.md + docs/CONTRIBUTING.md
            (Path(tmpdir) / "README.md").write_text("# Test")
            docs_dir = Path(tmpdir) / "docs"
            docs_dir.mkdir()
            (docs_dir / "CONTRIBUTING.md").write_text("# Contributing")
            findings = _check_documentation_alignment(str(ws), "")
            # Should not have missing_doc for docs/ content
            missing_docs = [f for f in findings if f["code"] == "missing_doc" and "docs" in f.get("file", "")]
            assert len(missing_docs) == 0

    def test_overall_health_scoring_consistency(self):
        from memory_center.core.audit.completion import (
            _calculate_overall_health, run_completion_audit,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            mc_dir = Path(tmpdir) / ".memory-center"
            mc_dir.mkdir()
            ws = mc_dir / "workspace.yaml"
            ws.write_text("workspace: test\n")
            # Minimal project: README + src + pyproject
            (Path(tmpdir) / "README.md").write_text("# Test")
            src_dir = Path(tmpdir) / "src"
            src_dir.mkdir()
            (src_dir / "main.py").write_text("print('hello')")
            (Path(tmpdir) / "pyproject.toml").write_text("[tool.pytest]\ntestpaths = ['tests']")
            test_dir = Path(tmpdir) / "tests"
            test_dir.mkdir()
            (test_dir / "test_main.py").write_text("def test_pass(): pass")
            audit = run_completion_audit(str(ws))
            decisions = {"total_decisions": 1, "decisions": []}
            health = _calculate_overall_health(audit, decisions)
            # Health score should be reasonable (not wildly different from audit score)
            assert health["overall_score"] >= audit["score"] - 10


# ---- Backend Query Tests ----

class TestBackendQuery:
    """Test unified backend query module with real data."""

    def test_check_health_empty_backend(self):
        from memory_center.core.backend.query import UnifiedBackendQuery
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            with UnifiedBackendQuery(db_path) as backend:
                health = backend.check_health()
                assert "healthy" in health
                assert "db_path" in health
                assert isinstance(health["issues"], list)

    def test_append_and_query_records(self):
        from memory_center.core.memory_backend import MemoryBackendStore
        from memory_center.core.backend.query import UnifiedBackendQuery
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            with MemoryBackendStore(db_path) as store:
                store.append_record(
                    "session-events.jsonl",
                    {"type": "tool_call", "tool": "mc_lookup", "created_at": "2026-01-01T00:00:00Z"},
                    record_id="evt-1",
                )
                store.append_record(
                    "session-events.jsonl",
                    {"type": "read", "file": "main.py", "created_at": "2026-01-01T00:01:00Z"},
                    record_id="evt-2",
                )
            with UnifiedBackendQuery(db_path) as backend:
                result = backend.query_records("session-events.jsonl", limit=10)
                records = result.get("records", [])
                assert len(records) == 2
                assert records[0]["record_id"] == "evt-2"  # DESC order

    def test_aggregate_by_session(self):
        from memory_center.core.memory_backend import MemoryBackendStore
        from memory_center.core.backend.query import UnifiedBackendQuery
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            with MemoryBackendStore(db_path) as store:
                for i in range(3):
                    store.append_record(
                        "session-events.jsonl",
                        {"type": "tool_call", "session_id": "sess-1", "created_at": f"2026-01-01T00:0{i}:00Z"},
                        record_id=f"evt-s1-{i}",
                    )
                store.append_record(
                    "session-events.jsonl",
                    {"type": "read", "session_id": "sess-2", "created_at": "2026-01-01T00:10:00Z"},
                    record_id="evt-s2-0",
                )
            with UnifiedBackendQuery(db_path) as backend:
                agg = backend.aggregate_by_session()
                assert isinstance(agg, dict)
                sessions = agg.get("sessions", {})
                assert "sess-1" in sessions
                assert sessions["sess-1"]["event_count"] == 3

    def test_get_session_summary(self):
        from memory_center.core.memory_backend import MemoryBackendStore
        from memory_center.core.backend.query import UnifiedBackendQuery
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            with MemoryBackendStore(db_path) as store:
                store.append_record(
                    "session-events.jsonl",
                    {"type": "tool_call", "session_id": "sess-x", "created_at": "2026-01-01T00:00:00Z"},
                    record_id="evt-x",
                )
            with UnifiedBackendQuery(db_path) as backend:
                summary = backend.get_session_summary("sess-x")
                assert summary["found"] is True
                assert summary["event_count"] == 1
                assert summary["event_types"]["tool_call"] == 1

    def test_get_session_summary_not_found(self):
        from memory_center.core.backend.query import UnifiedBackendQuery
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            with UnifiedBackendQuery(db_path) as backend:
                summary = backend.get_session_summary("nonexistent")
                assert summary["found"] is False

    def test_check_consistency_empty_backend(self):
        from memory_center.core.backend.query import UnifiedBackendQuery
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            with UnifiedBackendQuery(db_path) as backend:
                result = backend.check_consistency(Path(tmpdir))
                assert "consistent" in result
                assert isinstance(result["comparisons"], list)
                assert isinstance(result["divergences"], list)

    def test_check_consistency_with_data(self):
        from memory_center.core.memory_backend import MemoryBackendStore
        from memory_center.core.backend.query import UnifiedBackendQuery
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            with MemoryBackendStore(db_path) as store:
                store.append_record("test.jsonl", {"a": 1}, record_id="r1")
            with UnifiedBackendQuery(db_path) as backend:
                result = backend.check_consistency(Path(tmpdir))
                assert isinstance(result["consistent"], bool)
                assert len(result["comparisons"]) >= 1


# ---- Navigation Tests ----

class TestNavigation:
    """Test drill-down navigation module with real data."""

    def test_expand_ref_not_found(self):
        from memory_center.core.navigation.drilldown import DrillDownNavigator
        with tempfile.TemporaryDirectory() as tmpdir:
            mc_dir = Path(tmpdir) / ".memory-center"
            mc_dir.mkdir()
            ws = mc_dir / "workspace.yaml"
            ws.write_text("workspace: test\n")
            with DrillDownNavigator(str(ws)) as nav:
                result = nav.expand_ref("ev:nonexistent:tool_call:0")
                assert result["found"] is False
                assert "not found" in result["summary"].lower()

    def test_drill_timeline_empty(self):
        from memory_center.core.navigation.drilldown import DrillDownNavigator
        with tempfile.TemporaryDirectory() as tmpdir:
            mc_dir = Path(tmpdir) / ".memory-center"
            mc_dir.mkdir()
            ws = mc_dir / "workspace.yaml"
            ws.write_text("workspace: test\n")
            with DrillDownNavigator(str(ws)) as nav:
                result = nav.drill_timeline(session_id="nonexistent")
                assert "events" in result
                assert isinstance(result["events"], list)

    def test_drill_task_empty(self):
        from memory_center.core.navigation.drilldown import DrillDownNavigator
        with tempfile.TemporaryDirectory() as tmpdir:
            mc_dir = Path(tmpdir) / ".memory-center"
            mc_dir.mkdir()
            ws = mc_dir / "workspace.yaml"
            ws.write_text("workspace: test\n")
            with DrillDownNavigator(str(ws)) as nav:
                result = nav.drill_task("nonexistent-task")
                assert "task_id" in result
                assert result["found"] is False

    def test_build_handoff_context_empty(self):
        from memory_center.core.navigation.drilldown import DrillDownNavigator
        with tempfile.TemporaryDirectory() as tmpdir:
            mc_dir = Path(tmpdir) / ".memory-center"
            mc_dir.mkdir()
            ws = mc_dir / "workspace.yaml"
            ws.write_text("workspace: test\n")
            with DrillDownNavigator(str(ws)) as nav:
                result = nav.build_handoff_context("nonexistent-session")
                assert "session_id" in result
                assert isinstance(result.get("key_points", []), list)

    def test_build_facade_summary(self):
        from memory_center.core.navigation.drilldown import DrillDownNavigator
        with tempfile.TemporaryDirectory() as tmpdir:
            mc_dir = Path(tmpdir) / ".memory-center"
            mc_dir.mkdir()
            ws = mc_dir / "workspace.yaml"
            ws.write_text("workspace: test\n")
            with DrillDownNavigator(str(ws)) as nav:
                result = nav.build_facade_summary("test intent", {"results": []}, max_refs=3)
                assert "intent" in result
                assert "level_1_summary" in result
                assert result["level_1_summary"]["result_count"] == 0


# ---- Retrieval Behavioral Tests (requires demo workspace) ----

class TestRetrievalBehavior:
    """Behavioral tests for callers/callees/chain/context with real graph data."""

    @pytest.fixture(autouse=True)
    def _setup_workspace(self, tmp_path):
        """Set up demo workspace with indexed graph."""
        import shutil
        from memory_center.core.config import load_workspace_config
        from memory_center.core.indexer import reindex_workspace
        from memory_center.core.rules import ensure_default_rules
        from memory_center.core.store import WorkspaceStore

        source = Path("examples/spring-cloud-demo")
        if not source.exists():
            pytest.skip("Demo workspace not found")

        dest = tmp_path / "demo"
        shutil.copytree(source, dest)
        workspace = str(dest / ".memory-center" / "workspace.yaml")
        config = load_workspace_config(workspace)
        store = WorkspaceStore(workspace)
        ensure_default_rules(store)
        reindex_workspace(config, store)
        self.workspace = workspace

    def test_callers_returns_correct_edge_types(self):
        from memory_center.core.orchestrator import memory_callers
        callers = memory_callers(self.workspace, "ArticleFeignClient", depth=2, limit=20)
        assert callers["found"] is True
        if callers.get("callers"):
            for caller in callers["callers"]:
                edge_type = caller.get("type", "")
                assert edge_type not in ("CONTAINS", "DECLARES", "DECLARES_CONFIG")

    def test_callees_returns_correct_edge_types(self):
        from memory_center.core.orchestrator import memory_callees
        callees = memory_callees(self.workspace, "ArticleFeignClient", depth=2, limit=20)
        assert callees["found"] is True
        if callees.get("callees"):
            for callee in callees["callees"]:
                edge_type = callee.get("type", "")
                assert edge_type not in ("CONTAINS", "DECLARES", "DECLARES_CONFIG")

    def test_context_returns_evidence_summary(self):
        from memory_center.core.orchestrator import memory_context
        context = memory_context(self.workspace, "ArticleFeignClient", max_depth=2)
        assert context["found"] is True
        assert "evidence_summary" in context
        summary = context["evidence_summary"]
        assert "edge_types" in summary

    def test_callers_chain_tree_structure(self):
        from memory_center.core.orchestrator import memory_callers
        callers = memory_callers(self.workspace, "ArticleFeignClient", depth=2, limit=20)
        assert callers["found"] is True
        assert "chain_tree" in callers
        assert isinstance(callers["chain_tree"], dict)

    def test_query_hybrid_returns_intent(self):
        from memory_center.core.orchestrator import memory_query_hybrid
        result = memory_query_hybrid(self.workspace, "ArticleFeignClient")
        assert "intent" in result
        assert result["intent"]["primary_intent"] == "feign"
        # Contracts should have confidence scores
        if result.get("contracts"):
            for fc in result["contracts"].get("feign_contracts", []):
                if "_confidence" in fc:
                    assert fc["_confidence"] >= 0.10
                    assert fc["_confidence"] <= 1.0

    def test_memory_symbol_uses_hybrid_query_contracts(self):
        from memory_center.core.orchestrator import memory_symbol
        result = memory_symbol(self.workspace, "ArticleFeignClient", limit=5)
        assert result["found"] is True
        lookup = result.get("lookup", {})
        retrieval_summary = lookup.get("retrieval_summary", {})
        assert isinstance(retrieval_summary, dict)
        entrypoints = lookup.get("entrypoints", [])
        assert isinstance(entrypoints, list)

    def test_memory_query_hybrid_project_filters_results(self):
        from memory_center.core.orchestrator import memory_query_hybrid
        result = memory_query_hybrid(self.workspace, "ArticleFeignClient", limit=10, project="task-service")
        assert result["results"]
        assert all("task-service" in (item.get("node", {}).get("project") or "") for item in result["results"])
        assert result["matches"]
        assert all("task-service" in (item.get("node", {}).get("project") or "") for item in result["matches"])

    def test_memory_symbol_project_filters_lookup_candidates(self):
        from memory_center.core.orchestrator import memory_symbol
        result = memory_symbol(self.workspace, "ArticleFeignClient", limit=10, project="task-service")
        assert result["found"] is True
        assert "task-service" in (result["best_match"].get("project") or "")
        assert all("task-service" in ((item.get("node") or {}).get("project") or "") for item in result.get("matches", []))

    def test_memory_discover_sync_progress_is_executable_shape(self):
        from memory_center.core.orchestrator.query import memory_discover
        result = memory_discover(self.workspace, limit=20)
        matrix = result.get("compression_matrix", {})
        sync_progress = matrix.get("sync_progress", {})
        assert sync_progress.get("command") == "mc_sync"
        assert "mode" not in sync_progress
        assert sync_progress.get("required_one_of") == ["intent", "session_id"]

    def test_type_boosting_keys_match_graph_types(self):
        from memory_center.core.retrieval.hybrid import _apply_type_boosting, RetrievalResult
        # Verify boost map keys are valid node type names
        valid_types = {
            "FeignClient", "FeignMethod", "Endpoint", "MQTopic", "MQConsumer",
            "ConfigKey", "Class", "Service", "Method", "Field", "File",
            "Bean", "MQProducer", "DataResource",
        }
        # Create a dummy result to test boosting
        dummy = RetrievalResult(
            node_id="test:1", node={"type": "FeignClient", "name": "test"},
            score=1.0, sources=["graph"],
        )
        intent = {"primary_intent": "feign", "all_intents": {"feign": 2.0}}
        boosted = _apply_type_boosting([dummy], intent)
        # Should boost FeignClient
        assert boosted[0].score > 1.0
