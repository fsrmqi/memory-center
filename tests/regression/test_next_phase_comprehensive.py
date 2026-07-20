"""Comprehensive tests for NEXT_PHASE_MASTER_PLAN phases A-G + external absorption.

Covers:
- Phase A: Ontology constraint layer (EntityValidator, semantic strength, multi-hop)
- Phase B: Retrieval quality (Feign/Service distinction, contracts confidence)
- Phase C: Context Pack / Freshness / Domain workflow
- Phase D: Benchmark trending (regression thresholds)
- Phase E: Completion audit (workspace type detection)
- Phase F: Timeline / Ref / Task UX (drill-down, verification loop)
- Phase G: SQLite main read path (backend query)
- External: ECC (workflow profiles, pattern promotion, heuristics)
- External: UA (explanation schema, persona adaptation)
- External: CG (freshness banner, watcher)
"""
from __future__ import annotations

# ═══════════════════════════════════════════════════════════════════════
# Phase A: Ontology Constraint Layer
# ═══════════════════════════════════════════════════════════════════════

class TestEntityValidator:
    """Test EntityValidator from ontology module."""

    def test_is_feign_entity_by_name(self):
        from memory_center.core.knowledge.ontology import EntityValidator
        assert EntityValidator.is_feign_entity("ArticleFeignClient") is True
        assert EntityValidator.is_feign_entity("FeignArticleService") is True
        assert EntityValidator.is_feign_entity("FeginAutomaticReviewTaskService") is True

    def test_is_feign_entity_by_annotation(self):
        from memory_center.core.knowledge.ontology import EntityValidator
        assert EntityValidator.is_feign_entity("SomeClient", metadata={"has_feign_annotation": True}) is True

    def test_is_feign_entity_by_node_type(self):
        from memory_center.core.knowledge.ontology import EntityValidator
        assert EntityValidator.is_feign_entity("foo", node_type="FeignClient") is True
        assert EntityValidator.is_feign_entity("foo", node_type="FeignMethod") is True

    def test_is_local_service(self):
        from memory_center.core.knowledge.ontology import EntityValidator
        assert EntityValidator.is_local_service("ArticleService", node_type="Class") is True
        assert EntityValidator.is_local_service("ArticleServiceImpl", node_type="Class") is True
        # Feign should NOT be local
        assert EntityValidator.is_local_service("ArticleFeignClient", node_type="Class") is False

    def test_validate_endpoint_path(self):
        from memory_center.core.knowledge.ontology import EntityValidator
        specific = EntityValidator.validate_endpoint_path("/api/users")
        assert specific["is_specific"] is True
        assert specific["confidence"] == 0.9
        vague = EntityValidator.validate_endpoint_path("/")
        assert vague["is_specific"] is False
        assert vague["confidence"] == 0.1

    def test_classify_entity_category(self):
        from memory_center.core.knowledge.ontology import EntityValidator
        assert EntityValidator.classify_entity_category("Service") == "structural"
        assert EntityValidator.classify_entity_category("Class") == "declarative"
        assert EntityValidator.classify_entity_category("Endpoint") == "contractual"
        assert EntityValidator.classify_entity_category("Bean") == "inferential"
        assert EntityValidator.classify_entity_category("SessionEvent") == "memory"
        assert EntityValidator.classify_entity_category("BusinessFlow") == "v3_extended"
        assert EntityValidator.classify_entity_category("Unknown") == "unknown"

    def test_validate_memory_layer(self):
        from memory_center.core.knowledge.ontology import EntityValidator
        assert EntityValidator.validate_memory_layer("SessionEvent")["layer"] == "L0"
        assert EntityValidator.validate_memory_layer("Handoff")["layer"] == "L1"
        assert EntityValidator.validate_memory_layer("Task")["layer"] == "L2"
        assert EntityValidator.validate_memory_layer("Foo")["is_memory_entity"] is False


class TestSemanticStrengthAnnotation:
    """Test annotate_semantic_strength and multi_hop_confidence."""

    def test_annotate_by_node_type(self):
        from memory_center.core.knowledge.ontology import annotate_semantic_strength
        results = [{"node": {"type": "Class"}, "type": "Class"}]
        annotated = annotate_semantic_strength(results)
        assert annotated[0]["semantic_strength"] == "fact"

    def test_annotate_by_edge_type(self):
        from memory_center.core.knowledge.ontology import annotate_semantic_strength
        results = [{"edge_type": "CALLS_METHOD"}]
        annotated = annotate_semantic_strength(results)
        assert annotated[0]["semantic_strength"] == "confirmed"

    def test_multi_hop_decay(self):
        from memory_center.core.knowledge.ontology import multi_hop_confidence
        assert multi_hop_confidence(1.0, 1) == 1.0
        assert multi_hop_confidence(1.0, 2) == 0.9
        assert multi_hop_confidence(1.0, 3) == 0.8
        assert multi_hop_confidence(1.0, 5) == 0.7  # 4+ hops

    def test_ontology_exports(self):
        from memory_center.core.knowledge.ontology import (
            edge_confidence_range,
            edge_strength,
            validate_edge_type,
            validate_node_type,
        )
        assert validate_node_type("Class") is True
        assert validate_node_type("FakeType") is False
        assert validate_edge_type("CALLS_METHOD") is True
        assert validate_edge_type("FAKE_EDGE") is False
        assert edge_strength("CALLS_METHOD") == "confirmed"
        lo, hi = edge_confidence_range("TRANSITIVELY_CALLS")
        assert lo < hi


# ═══════════════════════════════════════════════════════════════════════
# Phase B: Retrieval Quality — intent detection
# ═══════════════════════════════════════════════════════════════════════

class TestQueryIntentDetection:
    """Test detect_query_intent with ontology-aware Feign detection."""

    def test_feign_intent(self):
        from memory_center.core.retrieval.hybrid import detect_query_intent
        result = detect_query_intent("ArticleFeignClient")
        assert result["primary_intent"] == "feign"

    def test_feign_typo(self):
        from memory_center.core.retrieval.hybrid import detect_query_intent
        result = detect_query_intent("FeginReviewService")
        assert result["primary_intent"] == "feign"

    def test_endpoint_intent(self):
        from memory_center.core.retrieval.hybrid import detect_query_intent
        result = detect_query_intent("/api/users controller")
        assert result["primary_intent"] == "endpoint"

    def test_mq_intent(self):
        from memory_center.core.retrieval.hybrid import detect_query_intent
        result = detect_query_intent("kafka topic 订单消息")
        assert result["primary_intent"] == "mq"

    def test_config_intent(self):
        from memory_center.core.retrieval.hybrid import detect_query_intent
        result = detect_query_intent("spring.datasource.url 配置")
        assert result["primary_intent"] == "config"

    def test_general_fallback(self):
        from memory_center.core.retrieval.hybrid import detect_query_intent
        result = detect_query_intent("hello world")
        assert result["primary_intent"] == "general"


# ═══════════════════════════════════════════════════════════════════════
# Phase C: Context Pack / Freshness / Domain
# ═══════════════════════════════════════════════════════════════════════

class TestFreshnessService:
    """Test IndexFreshnessService."""

    def test_freshness_status_fields(self):
        from memory_center.core.freshness.status import FreshnessStatus
        s = FreshnessStatus(status="fresh", message="ok")
        d = s.to_dict()
        assert d["status"] == "fresh"
        assert d["message"] == "ok"
        assert "changed_files" in d

    def test_watcher_status(self):
        import tempfile

        from memory_center.core.freshness.watcher import FileWatcher
        with tempfile.TemporaryDirectory() as td:
            w = FileWatcher(td)
            st = w.status()
            assert st["running"] is False
            assert st["tracked_files"] == 0


class TestDomainExtractor:
    """Test domain flow extraction classes."""

    def test_flow_node(self):
        from memory_center.core.domain.flow import FlowNode
        n = FlowNode(node_id="n1", name="svc", node_type="Service")
        d = n.to_dict()
        assert d["node_id"] == "n1"
        assert d["type"] == "Service"

    def test_flow_edge(self):
        from memory_center.core.domain.flow import FlowEdge
        e = FlowEdge(source_id="a", target_id="b", edge_type="CALLS", confidence=0.9)
        d = e.to_dict()
        assert d["confidence"] == 0.9

    def test_flow_path(self):
        from memory_center.core.domain.flow import FlowPath
        p = FlowPath(path_id="p1", nodes=["a", "b"], edge_types=["CALLS"])
        d = p.to_dict()
        assert d["depth"] == 2


# ═══════════════════════════════════════════════════════════════════════
# Phase D: Benchmark Trending
# ═══════════════════════════════════════════════════════════════════════

class TestBenchmarkTrending:
    """Test benchmark trending module."""

    def test_detect_regressions_empty(self):
        from memory_center.core.benchmark.trending import _detect_regressions
        result = _detect_regressions({})
        assert result == []

    def test_build_trend_summary(self):
        from memory_center.core.benchmark.trending import _build_trend_summary
        trends = {
            "fn_a": [{"savings_pct": 50}, {"savings_pct": 60}],
            "fn_b": [{"savings_pct": 20}],
        }
        summary = _build_trend_summary(trends)
        assert summary["functions_tracked"] == 2
        assert summary["total_trend_points"] == 3


# ═══════════════════════════════════════════════════════════════════════
# Phase E: Completion Audit
# ═══════════════════════════════════════════════════════════════════════

class TestCompletionAudit:
    """Test workspace type detection."""

    def test_detect_workspace_type_unknown(self):
        import tempfile
        from pathlib import Path

        from memory_center.core.audit.reports import detect_workspace_type
        with tempfile.TemporaryDirectory() as td:
            assert detect_workspace_type(Path(td)) == "unknown"


# ═══════════════════════════════════════════════════════════════════════
# Phase F: Timeline / Ref / Task UX — Verification Loop
# ═══════════════════════════════════════════════════════════════════════

class TestVerificationLoop:
    """Test ECC-2 verification loop."""

    def test_checklist_types(self):
        from memory_center.core.verification.loop import VerificationLoop
        # Can instantiate without workspace for checklist
        code_items = VerificationLoop.__init__.__code__.co_varnames  # just checking import
        assert "workspace_file" in code_items

    def test_checklist_content(self):
        from memory_center.core.verification.loop import VerificationLoop
        # Test static checklist retrieval via class
        loop = VerificationLoop.__new__(VerificationLoop)
        items = loop.get_checklist("bugfix")
        assert len(items) > 0
        assert any("根本原因" in i for i in items)


# ═══════════════════════════════════════════════════════════════════════
# External: ECC — Workflow Profiles
# ═══════════════════════════════════════════════════════════════════════

class TestWorkflowProfiles:
    """Test ECC-1 workflow protocol profiles."""

    def test_builtin_profiles_count(self):
        from memory_center.core.verification.workflow_profiles import BUILTIN_PROFILES
        assert len(BUILTIN_PROFILES) >= 4

    def test_quick_fix_profile(self):
        from memory_center.core.verification.workflow_profiles import get_workflow_profile
        p = get_workflow_profile("quick-fix")
        assert p is not None
        assert "mc_lookup" in p.tools_sequence

    def test_recommend_workflow(self):
        from memory_center.core.verification.workflow_profiles import recommend_workflow
        p = recommend_workflow("修复一个 Feign 接口 bug")
        assert p.name in ("quick-fix", "contract-change", "long-task", "architecture")

    def test_contract_change_profile(self):
        from memory_center.core.verification.workflow_profiles import get_workflow_profile
        p = get_workflow_profile("contract-change")
        assert p is not None
        assert "group_chain" in p.tools_sequence


# ═══════════════════════════════════════════════════════════════════════
# External: ECC — Pattern Promotion & Heuristics
# ═══════════════════════════════════════════════════════════════════════

class TestPatternPromotion:
    """Test ECC-3 pattern promotion."""

    def test_propose_structure(self):
        from memory_center.core.verification.pattern_promotion import PatternPromotion
        p = PatternPromotion.__new__(PatternPromotion)
        # Verify the class has propose method
        assert hasattr(p, "propose")
        assert hasattr(p, "promote")
        assert hasattr(p, "list_proposals")


class TestHeuristicsRegister:
    """Test ECC-4 learned heuristics."""

    def test_register_structure(self):
        from memory_center.core.verification.heuristics import HeuristicsRegister
        h = HeuristicsRegister.__new__(HeuristicsRegister)
        assert hasattr(h, "record")
        assert hasattr(h, "query")
        assert hasattr(h, "update_confidence")


# ═══════════════════════════════════════════════════════════════════════
# External: UA — Explanation Schema
# ═══════════════════════════════════════════════════════════════════════

class TestExplanationSchema:
    """Test UA-2 unified explanation schema."""

    def test_explanation_creation(self):
        from memory_center.core.explanation.schema import Explanation
        e = Explanation(
            subject="test",
            summary="这是一个测试",
            semantic_strength="inferred",
            confidence=0.8,
        )
        assert e.subject == "test"
        assert e.confidence == 0.8

    def test_explanation_compact(self):
        from memory_center.core.explanation.schema import Explanation
        e = Explanation(subject="x", summary="y", next_actions=["a", "b", "c", "d"])
        c = e.to_compact()
        assert "subject" in c
        assert len(c["next_actions"]) <= 3

    def test_explanation_full(self):
        from memory_center.core.explanation.schema import Explanation
        e = Explanation(subject="x", summary="y", evidence=[{"k": "v"}])
        f = e.to_full()
        assert len(f["evidence"]) == 1

    def test_persona_adaptation(self):
        from memory_center.core.explanation.schema import Explanation
        e = Explanation(
            subject="x", summary="y",
            next_actions=["检查依赖关系", "运行测试", "部署上线"],
        )
        arch = e.adapt_for_persona("architect")
        assert arch.persona == "architect"
        assert "架构视角" in arch.summary


# ═══════════════════════════════════════════════════════════════════════
# External: UA — Guided Tour
# ═══════════════════════════════════════════════════════════════════════

class TestGuidedTour:
    """Test UA-1 guided tour / onboarding."""

    def test_tour_step(self):
        from memory_center.core.onboarding.tour import TourStep
        s = TourStep(step_id=1, title="概览", description="项目概览")
        d = s.to_dict()
        assert d["step_id"] == 1

    def test_architecture_tour(self):
        from memory_center.core.onboarding.tour import ArchitectureTour
        t = ArchitectureTour(tour_id="t1", persona="developer", scope="workspace")
        d = t.to_dict()
        assert d["total_steps"] == 0


# ═══════════════════════════════════════════════════════════════════════
# External: CG — Reasoning modules
# ═══════════════════════════════════════════════════════════════════════

class TestReasoningModules:
    """Test graph patterns, risk, and transitive inference (already existing)."""

    def test_imports(self):
        from memory_center.core.reasoning.patterns import GraphPatternEngine
        from memory_center.core.reasoning.risk import RiskPatternEngine
        from memory_center.core.reasoning.transitive import TransitiveInferenceEngine
        assert GraphPatternEngine is not None
        assert RiskPatternEngine is not None
        assert TransitiveInferenceEngine is not None


# ═══════════════════════════════════════════════════════════════════════
# Hybrid retrieval imports
# ═══════════════════════════════════════════════════════════════════════

class TestHybridRetrievalImports:
    """Verify hybrid retrieval correctly imports from ontology."""

    def test_ontology_import_in_hybrid(self):
        from memory_center.core.retrieval import hybrid
        assert hasattr(hybrid, "EntityValidator")
        assert hasattr(hybrid, "annotate_semantic_strength")
        assert hasattr(hybrid, "multi_hop_confidence")
        assert hasattr(hybrid, "EDGE_SEMANTIC_STRENGTH")

    def test_edge_strength_merged(self):
        from memory_center.core.retrieval.hybrid import _EDGE_SEMANTIC_STRENGTH
        # Should have both old and new edge types
        assert "CALLS_METHOD" in _EDGE_SEMANTIC_STRENGTH
        assert "DECLARES" in _EDGE_SEMANTIC_STRENGTH


# ═══════════════════════════════════════════════════════════════════════
# Phase D: Benchmark — RegressionThresholdConfig
# ═══════════════════════════════════════════════════════════════════════

class TestRegressionThresholdConfig:
    """Test Phase D configurable regression thresholds."""

    def test_default_threshold(self):
        from memory_center.core.benchmark.trending import RegressionThresholdConfig
        cfg = RegressionThresholdConfig()
        assert cfg.default_threshold_pct == 10.0
        assert cfg.critical_threshold_pct == 25.0
        assert cfg.min_data_points == 5

    def test_per_function_threshold(self):
        from memory_center.core.benchmark.trending import RegressionThresholdConfig
        cfg = RegressionThresholdConfig(
            per_function_thresholds={"mc_lookup": 5.0, "mc_analyze": 15.0}
        )
        assert cfg.threshold_for("mc_lookup") == 5.0
        assert cfg.threshold_for("mc_analyze") == 15.0
        assert cfg.threshold_for("unknown_fn") == 10.0  # falls back to default


# ═══════════════════════════════════════════════════════════════════════
# Phase E: Audit — Enhanced workspace type detection
# ═══════════════════════════════════════════════════════════════════════

class TestEnhancedWorkspaceDetection:
    """Test Phase E improved workspace type detection."""

    def test_detect_unknown_for_empty(self):
        import tempfile
        from pathlib import Path

        from memory_center.core.audit.reports import detect_workspace_type
        with tempfile.TemporaryDirectory() as td:
            assert detect_workspace_type(Path(td)) == "unknown"

    def test_detect_python_with_pyproject(self):
        import tempfile
        from pathlib import Path

        from memory_center.core.audit.reports import detect_workspace_type
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "pyproject.toml").write_text("[project]\nname='test'")
            assert detect_workspace_type(Path(td)) == "python"

    def test_detect_node_with_package_json(self):
        import tempfile
        from pathlib import Path

        from memory_center.core.audit.reports import detect_workspace_type
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "package.json").write_text('{"name":"test"}')
            assert detect_workspace_type(Path(td)) == "node"

    def test_detect_scala_with_build_sbt(self):
        import tempfile
        from pathlib import Path

        from memory_center.core.audit.reports import detect_workspace_type
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "build.sbt").write_text('name := "test"')
            assert detect_workspace_type(Path(td)) == "scala"

    def test_detect_monorepo_with_pnpm_workspace(self):
        import tempfile
        from pathlib import Path

        from memory_center.core.audit.reports import detect_workspace_type
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "pnpm-workspace.yaml").write_text("packages:\n  - apps/*")
            assert detect_workspace_type(Path(td)) == "monorepo"

    def test_detect_java_maven(self):
        import tempfile
        from pathlib import Path

        from memory_center.core.audit.reports import detect_workspace_type
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "pom.xml").write_text('<project><artifactId>test</artifactId></project>')
            assert detect_workspace_type(Path(td)) == "java-maven"

    def test_detect_java_gradle(self):
        import tempfile
        from pathlib import Path

        from memory_center.core.audit.reports import detect_workspace_type
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "build.gradle").write_text('apply plugin: "java"')
            assert detect_workspace_type(Path(td)) == "java-gradle"


# ═══════════════════════════════════════════════════════════════════════
# Phase F: DrillDown behavioral tests
# ═══════════════════════════════════════════════════════════════════════

class TestDrillDownBehavioral:
    """Phase F: behavioral tests for DrillDownNavigator."""

    def test_build_facade_summary_empty(self):
        from memory_center.core.navigation.drilldown import DrillDownNavigator
        nav = DrillDownNavigator.__new__(DrillDownNavigator)
        summary = nav.build_facade_summary("lookup", {"results": []})
        assert summary["intent"] == "lookup"
        assert summary["level_1_summary"]["result_count"] == 0

    def test_build_facade_summary_with_results(self):
        from memory_center.core.navigation.drilldown import DrillDownNavigator
        nav = DrillDownNavigator.__new__(DrillDownNavigator)
        results = {
            "results": [
                {"node": {"type": "Class", "name": "UserService", "project": "auth"}, "score": 0.85},
                {"node": {"type": "Method", "name": "getUser", "project": "auth"}, "score": 0.70},
            ]
        }
        summary = nav.build_facade_summary("feign query", results)
        assert summary["level_1_summary"]["result_count"] == 2
        assert summary["level_1_summary"]["top_match"]["name"] == "UserService"

    def test_suggest_quick_action_feign(self):
        from memory_center.core.navigation.drilldown import DrillDownNavigator
        nav = DrillDownNavigator.__new__(DrillDownNavigator)
        action = nav._suggest_quick_action("feign client", {"results": [{"node": {}}]})
        assert "Feign" in action or "feign" in action.lower()

    def test_suggest_quick_action_empty(self):
        from memory_center.core.navigation.drilldown import DrillDownNavigator
        nav = DrillDownNavigator.__new__(DrillDownNavigator)
        action = nav._suggest_quick_action("anything", {"results": []})
        assert "更具体" in action


# ═══════════════════════════════════════════════════════════════════════
# Phase G: Backend unified query
# ═══════════════════════════════════════════════════════════════════════

class TestBackendQuery:
    """Phase G: UnifiedBackendQuery structure tests."""

    def test_import_unified_backend_query(self):
        from memory_center.core.backend.query import UnifiedBackendQuery
        assert UnifiedBackendQuery is not None

    def test_has_required_methods(self):
        from memory_center.core.backend.query import UnifiedBackendQuery
        assert hasattr(UnifiedBackendQuery, 'query_records')
        assert hasattr(UnifiedBackendQuery, 'query_session_events')
        assert hasattr(UnifiedBackendQuery, 'query_write_receipts')
        assert hasattr(UnifiedBackendQuery, 'check_health')


# ═══════════════════════════════════════════════════════════════════════
# External: ECC — Persona & incremental refresh
# ═══════════════════════════════════════════════════════════════════════

class TestPersonaAdaptation:
    """UA-5 persona profiles for explanations."""

    def test_architect_persona(self):
        from memory_center.core.explanation.schema import Explanation
        e = Explanation(
            subject="auth module", summary="Auth模块依赖关系",
            next_actions=["检查依赖关系", "运行测试", "部署上线"]
        )
        arch = e.adapt_for_persona("architect")
        assert arch.persona == "architect"
        assert "架构视角" in arch.summary

    def test_manager_persona(self):
        from memory_center.core.explanation.schema import Explanation
        e = Explanation(
            subject="auth module", summary="Auth模块",
            next_actions=["检查影响面", "运行测试"]
        )
        mgr = e.adapt_for_persona("manager")
        assert mgr.persona == "manager"
        assert "管理视角" in mgr.summary

    def test_developer_persona_unchanged(self):
        from memory_center.core.explanation.schema import Explanation
        e = Explanation(subject="x", summary="y", next_actions=["a"])
        dev = e.adapt_for_persona("developer")
        assert dev.persona == "developer"
        assert dev.summary == "y"


# ═══════════════════════════════════════════════════════════════════════
# External: CG — Watcher & incremental reindex
# ═══════════════════════════════════════════════════════════════════════

class TestWatcherBridge:
    """CG-4 watcher-to-incremental-reindex bridge."""

    def test_watcher_status_structure(self):
        import tempfile

        from memory_center.core.freshness.watcher import FileWatcher
        with tempfile.TemporaryDirectory() as td:
            w = FileWatcher(td, extensions=(".py",))
            st = w.status()
            assert "running" in st
            assert "tracked_files" in st
            assert "poll_interval" in st

    def test_watcher_detect_changes_empty(self):
        import tempfile

        from memory_center.core.freshness.watcher import FileWatcher
        with tempfile.TemporaryDirectory() as td:
            w = FileWatcher(td, extensions=(".py",))
            events = w.detect_changes()
            assert isinstance(events, list)

    def test_watch_event_structure(self):
        from memory_center.core.freshness.watcher import WatchEvent
        e = WatchEvent(path="src/Main.java", change_type="modified")
        assert e.path == "src/Main.java"
        assert e.change_type == "modified"
        assert e.detected_at > 0
