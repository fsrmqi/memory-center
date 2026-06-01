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


# ---- Backend Query Tests ----

class TestBackendQuery:
    """Test unified backend query module."""

    def test_unified_backend_query_class_exists(self):
        from memory_center.core.backend.query import UnifiedBackendQuery
        assert hasattr(UnifiedBackendQuery, 'read_index')
        assert hasattr(UnifiedBackendQuery, 'query_records')
        assert hasattr(UnifiedBackendQuery, 'query_session_events')
        assert hasattr(UnifiedBackendQuery, 'query_write_receipts')
        assert hasattr(UnifiedBackendQuery, 'aggregate_by_session')
        assert hasattr(UnifiedBackendQuery, 'aggregate_by_project')
        assert hasattr(UnifiedBackendQuery, 'check_health')
        assert hasattr(UnifiedBackendQuery, 'query_timeline')
        assert hasattr(UnifiedBackendQuery, 'get_session_summary')


# ---- Navigation Tests ----

class TestNavigation:
    """Test drill-down navigation module."""

    def test_drilldown_navigator_class_exists(self):
        from memory_center.core.navigation.drilldown import DrillDownNavigator
        assert hasattr(DrillDownNavigator, 'expand_ref')
        assert hasattr(DrillDownNavigator, 'drill_timeline')
        assert hasattr(DrillDownNavigator, 'drill_task')
        assert hasattr(DrillDownNavigator, 'build_handoff_context')
        assert hasattr(DrillDownNavigator, 'build_facade_summary')
