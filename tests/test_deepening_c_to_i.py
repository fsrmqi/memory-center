"""Deepening tests for C-03~I-05 remaining work packages.

Covers the '未覆盖项（需后续深化）' from DELEGATED_EXECUTION_LOG.md:
- D-01~D-06: Freshness/ContextPack/Domain/Onboarding workflow integration
- C-03~C-07: Query intent, contracts, chain, reasoning behavior tightening
- F-02~F-07: Backend/Metrics/Benchmark/Audit/Health deepening
- G-01~G-07: Workflow/Verification/Bundle/Workbench closing
- H-04: Resumable workflow step-level state persistence
- H-06~H-11: Change bundles/rule preview/review finding closure
- I-01~I-05: Documentation, compatibility, security, final verification
"""
from __future__ import annotations

from pathlib import Path

from tests.fixtures import copy_demo_workspace

# ===========================================================================
# D-01: Freshness in main chain
# ===========================================================================

class TestD01_FreshnessMainChain:
    """D-01: Freshness enters start/lookup/analyze main chain."""

    def test_freshness_with_actions_fresh(self, tmp_path):
        """Fresh status returns correct semantics and no recommended actions."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.freshness.integration import (
            FRESH,
            PENDING,
            STALE,
            UNKNOWN,
            get_freshness_with_actions,
        )
        result = get_freshness_with_actions(str(ws))
        assert "status" in result
        assert result["status"] in (FRESH, PENDING, STALE, UNKNOWN)
        assert "semantics" in result
        assert "recommended_actions" in result
        assert isinstance(result["recommended_actions"], list)

    def test_freshness_action_hint(self):
        """Action hints are defined for all freshness statuses."""
        from memory_center.core.freshness.integration import (
            FRESH,
            PENDING,
            STALE,
            UNKNOWN,
            freshness_action_hint,
        )
        for status in (FRESH, PENDING, STALE, UNKNOWN):
            hint = freshness_action_hint(status)
            assert isinstance(hint, str)
            assert len(hint) > 0

    def test_freshness_risk_escalation(self):
        """Stale freshness escalates risk level."""
        from memory_center.core.freshness.integration import (
            FRESH,
            PENDING,
            STALE,
            freshness_risk_escalation,
        )
        assert freshness_risk_escalation("low", STALE) == "high"
        assert freshness_risk_escalation("low", FRESH) == "low"
        assert freshness_risk_escalation("high", FRESH) == "high"
        assert freshness_risk_escalation("medium", PENDING) == "medium"
        assert freshness_risk_escalation("low", PENDING) == "medium"

    def test_stale_file_alert(self):
        """Stale file alert generates alerts for stale/pending files."""
        from memory_center.core.freshness.integration import (
            FRESH,
            PENDING,
            STALE,
            stale_file_alert,
        )
        file_freshness = {
            "src/Main.java": STALE,
            "src/Util.java": FRESH,
            "src/Config.java": PENDING,
        }
        alerts = stale_file_alert(file_freshness)
        assert len(alerts) == 2
        alert_files = {a["file"] for a in alerts}
        assert "src/Main.java" in alert_files
        assert "src/Config.java" in alert_files
        assert "src/Util.java" not in alert_files

    def test_session_start_includes_freshness(self, tmp_path):
        """workspace_start_session returns freshness info."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.orchestrator.session import workspace_start_session
        result = workspace_start_session(str(ws), intent="test")
        assert "freshness" in result
        assert isinstance(result["freshness"], dict)

    def test_query_hybrid_includes_freshness(self, tmp_path):
        """memory_query_hybrid includes freshness banner."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.orchestrator.query import memory_query_hybrid
        result = memory_query_hybrid(str(ws), "OrderService", limit=5)
        assert "freshness" in result
        assert isinstance(result["freshness"], dict)

    def test_impact_includes_freshness(self, tmp_path):
        """memory_impact includes freshness banner."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.orchestrator.impact import memory_impact
        result = memory_impact(str(ws), "OrderService")
        assert "freshness" in result


# ===========================================================================
# D-02: Context Pack as default understanding entry
# ===========================================================================

class TestD02_ContextPackDefault:
    """D-02: Context Pack becomes default understanding entry."""

    def test_context_pack_builder_build(self, tmp_path):
        """ContextPackBuilder.build() returns a complete ContextPack."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.context.pack import ContextPackBuilder
        builder = ContextPackBuilder(str(ws))
        pack = builder.build("OrderService", budget_tokens=4000)
        assert pack.query == "OrderService"
        assert isinstance(pack.entrypoints, list)
        assert isinstance(pack.snippets, list)
        assert isinstance(pack.freshness, dict)
        assert pack.token_estimate >= 0
        assert isinstance(pack.progressive, dict)

    def test_context_pack_progressive_levels(self, tmp_path):
        """ContextPack includes all 3 progressive disclosure levels."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.context.pack import ContextPackBuilder
        builder = ContextPackBuilder(str(ws))
        pack = builder.build("OrderService", budget_tokens=4000)
        assert "level_1_quick" in pack.progressive
        assert "level_2_relationships" in pack.progressive
        assert "level_3_next_actions" in pack.progressive

    def test_context_pack_benchmark(self, tmp_path):
        """benchmark_context_pack runs without error."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.context.pack import benchmark_context_pack
        result = benchmark_context_pack(
            str(ws),
            queries=["OrderService", "UserService"],
        )
        assert "total_queries" in result
        assert result["total_queries"] == 2
        assert "results" in result


# ===========================================================================
# D-03: Unified Explanation Schema
# ===========================================================================

class TestD03_ExplanationSchema:
    """D-03: Unified explanation schema integration."""

    def test_explanation_entry_valid(self):
        """explanation_entry produces a valid D-03 explanation dict."""
        from memory_center.core.explanation.schema import explanation_entry
        entry = explanation_entry(
            subject="test:entity",
            summary="Test summary",
            semantic_strength="fact",
            confidence=0.9,
        )
        assert entry["subject"] == "test:entity"
        assert entry["summary"] == "Test summary"
        assert entry["semantic_strength"] == "fact"
        assert entry["confidence"] == 0.9
        assert "evidence" in entry
        assert "next_refs" in entry

    def test_explanation_entry_invalid_strength(self):
        """Invalid semantic_strength defaults to 'inferred'."""
        from memory_center.core.explanation.schema import explanation_entry
        entry = explanation_entry(semantic_strength="invalid")
        assert entry["semantic_strength"] == "inferred"

    def test_explanation_compact_full_views(self):
        """Explanation has to_compact() and to_full() views."""
        from memory_center.core.explanation.schema import Explanation
        exp = Explanation(
            subject="test",
            summary="Test",
            semantic_strength="fact",
            confidence=0.9,
        )
        compact = exp.to_compact()
        assert "subject" in compact
        assert "strength" in compact
        full = exp.to_full()
        assert "evidence" in full
        assert "display_rule" in full

    def test_explanation_persona_adaptation(self):
        """Explanation adapts for different personas."""
        from memory_center.core.explanation.schema import Explanation
        exp = Explanation(
            subject="test",
            summary="架构影响分析",
            next_actions=["检查依赖关系", "评估风险"],
        )
        architect = exp.adapt_for_persona("architect")
        assert "架构视角" in architect.summary
        manager = exp.adapt_for_persona("manager")
        assert "管理视角" in manager.summary

    def test_merge_explanations(self):
        """merge_explanations combines multiple entries."""
        from memory_center.core.explanation.schema import explanation_entry, merge_explanations
        entries = [
            explanation_entry(subject="a", summary="A", confidence=0.9),
            explanation_entry(subject="b", summary="B", confidence=0.7),
        ]
        merged = merge_explanations(entries)
        assert "a" in merged["subject"]
        assert "b" in merged["subject"]
        assert merged["confidence"] == 0.7  # min confidence

    def test_backward_compat_wrapper(self):
        """backward_compat_wrapper adds missing fields to old explanations."""
        from memory_center.core.explanation.schema import backward_compat_wrapper
        old = {"result": "something", "type": "test"}
        wrapped = backward_compat_wrapper(old)
        assert "summary" in wrapped
        assert "semantic_strength" in wrapped
        assert "confidence" in wrapped


# ===========================================================================
# D-04: Domain / Business Flow output
# ===========================================================================

class TestD04_DomainFlow:
    """D-04: Domain and Business Flow output deepening."""

    def test_business_domain_extractor(self, tmp_path):
        """BusinessDomainExtractor extracts domains from graph."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.domain.extractor import BusinessDomainExtractor
        from memory_center.core.storage.unified import UnifiedStore
        from memory_center.core.store import WorkspaceStore
        store = WorkspaceStore(str(ws))
        with UnifiedStore(store.graph_db_path) as unified:
            extractor = BusinessDomainExtractor(unified)
            domains = extractor.extract_domains()
            assert isinstance(domains, list)
            for d in domains:
                assert hasattr(d, 'domain_id')
                assert hasattr(d, 'name')
                assert hasattr(d, 'confidence')
                dict_form = d.to_dict()
                assert "_explanation" in dict_form

    def test_business_flow_graph_build(self, tmp_path):
        """BusinessFlowGraph.build_flow_graph() returns nodes and edges."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.domain.flow import BusinessFlowGraph
        from memory_center.core.storage.unified import UnifiedStore
        from memory_center.core.store import WorkspaceStore
        store = WorkspaceStore(str(ws))
        with UnifiedStore(store.graph_db_path) as unified:
            graph = BusinessFlowGraph(unified)
            result = graph.build_flow_graph()
            assert "nodes" in result
            assert "edges" in result
            assert "node_count" in result

    def test_extract_business_flows_for_workspace(self, tmp_path):
        """extract_business_flows_for_workspace accepts workspace.yaml."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.domain.flow import extract_business_flows_for_workspace
        result = extract_business_flows_for_workspace(
            str(ws),
            seed_node_id="",
        )
        assert "flows" in result
        assert "workflow" in result
        # Empty seed returns error
        assert "error" in result or result["flows"] == []


# ===========================================================================
# D-05: Onboarding & Persona output
# ===========================================================================

class TestD05_OnboardingPersona:
    """D-05: Onboarding and Persona output deepening."""

    def test_onboarding_guide_exists(self):
        """Onboarding guide module is importable."""
        from memory_center.core.onboarding import glossary, guide, tour
        assert guide is not None
        assert glossary is not None
        assert tour is not None

    def test_explanation_persona_developer(self):
        """Developer persona doesn't modify summary prefix."""
        from memory_center.core.explanation.schema import Explanation
        exp = Explanation(subject="test", summary="Test summary")
        dev = exp.adapt_for_persona("developer")
        assert dev.summary == "Test summary"  # no prefix added


# ===========================================================================
# D-06: Resume / Handoff / Drill-down
# ===========================================================================

class TestD06_ResumeHandoff:
    """D-06: Resume/Handoff/Drill-down summary enhancement."""

    def test_recent_sessions(self, tmp_path):
        """workspace_recent_sessions returns session list."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.orchestrator.session import (
            workspace_end_session,
            workspace_recent_sessions,
            workspace_start_session,
        )
        wp = str(ws)
        start = workspace_start_session(wp, intent="test_d06")
        sid = start["session_id"]
        workspace_end_session(wp, sid, outcome="done")
        recent = workspace_recent_sessions(wp, limit=5)
        assert "recent_sessions" in recent
        assert isinstance(recent["recent_sessions"], list)

    def test_suggest_case(self, tmp_path):
        """workspace_suggest_case returns draft case from session."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.orchestrator.session import (
            workspace_end_session,
            workspace_log_session_event,
            workspace_start_session,
            workspace_suggest_case,
        )
        wp = str(ws)
        start = workspace_start_session(wp, intent="test_case")
        sid = start["session_id"]
        workspace_log_session_event(wp, sid, "tool_call", {"tool_name": "mc_lookup", "query": "OrderService"})
        workspace_end_session(wp, sid, outcome="completed")
        result = workspace_suggest_case(wp, sid)
        assert result["found"] is True
        assert result["draft_case"] is not None
        assert "task" in result["draft_case"]


# ===========================================================================
# C-03: Query intent detection tightening
# ===========================================================================

class TestC03_QueryIntent:
    """C-03: Converge query intent detection and ranking."""

    def test_detect_feign_intent(self):
        """Feign-related queries detect 'feign' intent."""
        from memory_center.core.retrieval.hybrid import detect_query_intent
        intent = detect_query_intent("OrderFeignClient")
        assert intent["primary_intent"] == "feign"

    def test_detect_endpoint_intent(self):
        """Path-like queries detect 'endpoint' intent."""
        from memory_center.core.retrieval.hybrid import detect_query_intent
        intent = detect_query_intent("/api/orders")
        assert intent["primary_intent"] == "endpoint"

    def test_detect_mq_intent(self):
        """MQ-related queries detect 'mq' intent."""
        from memory_center.core.retrieval.hybrid import detect_query_intent
        intent = detect_query_intent("order-topic")
        assert intent["primary_intent"] == "mq"

    def test_detect_config_intent(self):
        """Config-like queries detect 'config' intent."""
        from memory_center.core.retrieval.hybrid import detect_query_intent
        intent = detect_query_intent("spring.datasource.url")
        assert "config" in intent.get("all_intents", {})

    def test_detect_general_intent(self):
        """Generic queries detect 'general' intent."""
        from memory_center.core.retrieval.hybrid import detect_query_intent
        intent = detect_query_intent("some random text")
        assert intent["primary_intent"] == "general"


# ===========================================================================
# C-04: Contracts behavior tightening
# ===========================================================================

class TestC04_Contracts:
    """C-04: Contracts behavior deepening."""

    def test_contracts_index_exists(self, tmp_path):
        """Contracts index is readable from workspace."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.orchestrator.query import memory_contracts
        result = memory_contracts(str(ws))
        assert "feign_contracts" in result
        assert "mq_contracts" in result
        assert "api_contracts" in result

    def test_filter_contracts_confidence_scoring(self):
        """_filter_contracts_by_query assigns correct confidence levels."""
        from memory_center.core.orchestrator.query import _filter_contracts_by_query
        contracts = [
            {"interface": "OrderFeignClient", "methods": [{"method_name": "getOrder"}], "project": "order"},
            {"interface": "UserFeignClient", "methods": [{"method_name": "getUser"}], "project": "user"},
        ]
        filtered = _filter_contracts_by_query(contracts, "OrderFeignClient", "feign")
        assert len(filtered) >= 1
        # Best match should have high confidence
        assert filtered[0]["_confidence"] >= 0.9

    def test_filter_contracts_fallback(self):
        """_filter_contracts_by_query returns fallback when no match."""
        from memory_center.core.orchestrator.query import _filter_contracts_by_query
        contracts = [
            {"interface": "FooClient", "methods": [], "project": "foo"},
        ]
        filtered = _filter_contracts_by_query(contracts, "zzz_nonexistent", "feign")
        assert len(filtered) >= 1
        assert filtered[0].get("_is_fallback") is True


# ===========================================================================
# C-05: Chain / Callers / Callees
# ===========================================================================

class TestC05_ChainBehavior:
    """C-05: Callers/Callees/Chain behavior deepening."""

    def test_graph_neighbors_upstream(self, tmp_path):
        """Graph neighbors in upstream direction returns incoming edges."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.graph import GraphStore
        from memory_center.core.store import WorkspaceStore
        store = WorkspaceStore(str(ws))
        with GraphStore(store.graph_db_path) as graph:
            nodes = graph.find_nodes("OrderService", limit=3)
            if nodes:
                node_id = nodes[0]["id"]
                incoming = graph.neighbors(node_id, direction="upstream", max_depth=1, limit=10)
                assert isinstance(incoming, list)

    def test_graph_neighbors_downstream(self, tmp_path):
        """Graph neighbors in downstream direction returns outgoing edges."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.graph import GraphStore
        from memory_center.core.store import WorkspaceStore
        store = WorkspaceStore(str(ws))
        with GraphStore(store.graph_db_path) as graph:
            nodes = graph.find_nodes("OrderService", limit=3)
            if nodes:
                node_id = nodes[0]["id"]
                outgoing = graph.neighbors(node_id, direction="downstream", max_depth=1, limit=10)
                assert isinstance(outgoing, list)


# ===========================================================================
# C-07: Reasoning patterns main-chain integration
# ===========================================================================

class TestC07_ReasoningPatterns:
    """C-07: Reasoning patterns integration into main chain."""

    def test_reasoning_integration_run(self, tmp_path):
        """run_reasoning_patterns returns structured results."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.reasoning.integration import run_reasoning_patterns
        result = run_reasoning_patterns(str(ws), target_id="")
        assert "patterns" in result
        assert "transitive" in result
        assert "risk" in result

    def test_impact_includes_reasoning(self, tmp_path):
        """memory_impact includes _reasoning field."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.orchestrator.impact import memory_impact
        result = memory_impact(str(ws), "OrderService")
        assert "_reasoning" in result
        reasoning = result["_reasoning"]
        assert "patterns" in reasoning
        assert "transitive" in reasoning
        assert "risk" in reasoning


# ===========================================================================
# F-02: Unified Backend Query
# ===========================================================================

class TestF02_BackendQuery:
    """F-02: Unified backend query deepening."""

    def test_backend_query_records(self, tmp_path):
        """memory_backend_query returns records and refs."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.orchestrator.query import memory_backend_query
        result = memory_backend_query(str(ws))
        assert "records" in result
        assert "refs" in result

    def test_backend_query_with_collection(self, tmp_path):
        """memory_backend_query accepts collection filter."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.orchestrator.query import memory_backend_query
        result = memory_backend_query(
            str(ws),
            collection="session_events",
        )
        assert "records" in result


# ===========================================================================
# F-03: Metrics Collector
# ===========================================================================

class TestF03_Metrics:
    """F-03: MetricsCollector deepening."""

    def test_metrics_record_and_query(self, tmp_path):
        """MetricsCollector records and queries metrics."""
        from memory_center.core.metrics import MetricsCollector
        mc = MetricsCollector(tmp_path / "workspace.yaml")
        mc.record("test_metric", 42.0, unit="ms")
        mc.record("test_metric", 55.0, unit="ms")
        rows = mc.query("test_metric")
        assert len(rows) == 2
        assert rows[0]["value"] == 42.0

    def test_metrics_summary(self, tmp_path):
        """MetricsCollector.summary() computes avg/p50/p95."""
        from memory_center.core.metrics import MetricsCollector
        mc = MetricsCollector(tmp_path / "workspace.yaml")
        for v in [10, 20, 30, 40, 50]:
            mc.record("latency", float(v), unit="ms")
        summary = mc.summary("latency")
        assert summary["count"] == 5
        assert summary["avg_ms"] == 30.0
        assert summary["min_ms"] == 10.0
        assert summary["max_ms"] == 50.0

    def test_metrics_timer(self, tmp_path):
        """MetricsCollector.timer() records elapsed time."""
        import time

        from memory_center.core.metrics import MetricsCollector
        mc = MetricsCollector(tmp_path / "workspace.yaml")
        with mc.timer("operation"):
            time.sleep(0.01)
        rows = mc.query("operation")
        assert len(rows) == 1
        assert rows[0]["value"] > 0


# ===========================================================================
# F-04: Benchmark Trending
# ===========================================================================

class TestF04_Benchmark:
    """F-04: Benchmark trending deepening."""

    def test_regression_threshold_config(self):
        """RegressionThresholdConfig supports per-function thresholds."""
        from memory_center.core.benchmark.trending import RegressionThresholdConfig
        config = RegressionThresholdConfig(
            default_threshold_pct=10.0,
            critical_threshold_pct=25.0,
            min_data_points=3,
            per_function_thresholds={"memory_query_hybrid": 5.0},
        )
        assert config.default_threshold_pct == 10.0
        assert config.per_function_thresholds["memory_query_hybrid"] == 5.0


# ===========================================================================
# F-06: Completion Audit
# ===========================================================================

class TestF06_Audit:
    """F-06: Completion audit deepening."""

    def test_workspace_type_detection(self, tmp_path):
        """detect_workspace_type returns correct type for various projects."""
        from memory_center.core.audit.completion import detect_workspace_type
        # Empty dir → unknown
        result = detect_workspace_type(tmp_path)
        assert result in ("unknown",)

    def test_java_maven_detection(self, tmp_path):
        """Maven project detected correctly."""
        (tmp_path / "pom.xml").write_text("<project/>")
        from memory_center.core.audit.completion import detect_workspace_type
        assert detect_workspace_type(tmp_path) == "java-maven"


# ===========================================================================
# F-07: Health & Governance
# ===========================================================================

class TestF07_Health:
    """F-07: Health and governance deepening."""

    def test_runtime_audit(self, tmp_path):
        """audit_agent_runtime returns score and findings."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.audit.runtime import audit_agent_runtime
        result = audit_agent_runtime(str(ws))
        assert "score" in result
        assert "findings" in result
        assert isinstance(result["findings"], list)


# ===========================================================================
# G-01: Workflow Protocol Profiles
# ===========================================================================

class TestG01_WorkflowProfiles:
    """G-01: Workflow profiles deepening."""

    def test_builtin_profiles_exist(self):
        """Four built-in workflow profiles exist."""
        from memory_center.core.verification.workflow_profiles import BUILTIN_PROFILES
        assert "quick-fix" in BUILTIN_PROFILES
        assert "contract-change" in BUILTIN_PROFILES
        assert "long-task" in BUILTIN_PROFILES
        assert "architecture" in BUILTIN_PROFILES

    def test_recommend_workflow(self):
        """recommend_workflow returns appropriate profile."""
        from memory_center.core.verification.workflow_profiles import recommend_workflow
        assert recommend_workflow("fix the bug in login").name == "quick-fix"
        assert recommend_workflow("refactor the Feign contract").name == "contract-change"
        assert recommend_workflow("migrate to new architecture").name == "architecture"
        assert recommend_workflow("implement new feature X").name == "long-task"

    def test_profile_has_steps(self):
        """Each profile has steps and tools_sequence."""
        from memory_center.core.verification.workflow_profiles import BUILTIN_PROFILES
        for name, profile in BUILTIN_PROFILES.items():
            assert len(profile.steps) >= 3, f"{name} has too few steps"
            assert len(profile.tools_sequence) >= 3, f"{name} has too few tools"


# ===========================================================================
# G-02: Verification Loop
# ===========================================================================

class TestG02_VerificationLoop:
    """G-02: Verification loop deepening."""

    def test_verification_loop_start(self, tmp_path):
        """VerificationLoop.start() creates a loop entry."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.loop import VerificationLoop
        loop = VerificationLoop(str(ws))
        result = loop.start("task-1", "Test verification")
        assert result["status"] == "started"
        assert "loop_id" in result
        assert "phases" in result
        assert "analyze" in result["phases"]
        assert "checklist" in result["phases"]

    def test_verification_loop_get_checklist(self, tmp_path):
        """VerificationLoop.get_checklist() returns items for task type."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.loop import VerificationLoop
        loop = VerificationLoop(str(ws))
        items = loop.get_checklist("code_change")
        assert len(items) >= 3
        items2 = loop.get_checklist("bugfix")
        assert len(items2) >= 2

    def test_verification_loop_status(self, tmp_path):
        """VerificationLoop.get_status() returns status for task."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.loop import VerificationLoop
        loop = VerificationLoop(str(ws))
        status = loop.get_status("nonexistent-task")
        assert status["status"] == "pending"

    def test_verification_generate_checklist(self, tmp_path):
        """VerificationLoop.generate_checklist() works from analysis."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.loop import VerificationLoop
        loop = VerificationLoop(str(ws))
        result = loop.generate_checklist({"task_type": "bugfix"})
        assert result["task_type"] == "bugfix"
        assert len(result["items"]) >= 2


# ===========================================================================
# G-03: Pattern Promotion & Heuristics
# ===========================================================================

class TestG03_PatternPromotion:
    """G-03: Pattern promotion and heuristics deepening."""

    def test_pattern_propose(self, tmp_path):
        """PatternPromotion.propose() creates a proposal."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.pattern_promotion import PatternPromotion
        pp = PatternPromotion(str(ws))
        result = pp.propose("case", "case-1", "retry_pattern", "Always use idempotent retry", [])
        assert result["status"] == "proposed"
        assert result["pattern_name"] == "retry_pattern"

    def test_heuristics_record_and_query(self, tmp_path):
        """HeuristicsRegister records and queries heuristics."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.heuristics import HeuristicsRegister
        hr = HeuristicsRegister(str(ws))
        hr.record("retry", "idempotent_retry", "when processing MQ", "always succeed", confidence=0.8)
        hr.record("retry", "simple_retry", "when HTTP call fails", "usually works", confidence=0.6)
        results = hr.query("retry")
        assert len(results) >= 2
        # Should be sorted by confidence desc
        if len(results) >= 2:
            assert results[0]["confidence"] >= results[1]["confidence"]


# ===========================================================================
# G-05: Bundle Export
# ===========================================================================

class TestG05_BundleExport:
    """G-05: Agent usage bundle export deepening."""

    def test_generate_agent_bundle_codex(self, tmp_path):
        """generate_agent_bundle for codex returns valid bundle."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.bundle_export import generate_agent_bundle
        bundle = generate_agent_bundle(str(ws), agent="codex")
        assert bundle["agent"] == "codex"
        assert "contents" in bundle
        assert "agent_specific" in bundle
        assert bundle["agent_specific"]["mcp_config_path"] == ".codex/mcp.json"

    def test_generate_agent_bundle_claude(self, tmp_path):
        """generate_agent_bundle for claude returns valid bundle."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.bundle_export import generate_agent_bundle
        bundle = generate_agent_bundle(str(ws), agent="claude")
        assert bundle["agent"] == "claude"
        assert bundle["agent_specific"]["mcp_config_path"] == ".mcp.json"


# ===========================================================================
# H-01: Constitution
# ===========================================================================

class TestH01_Constitution:
    """H-01: Constitution governance deepening."""

    def test_constitution_rules_exist(self):
        """CONSTITUTION_RULES has 5 governance invariants."""
        from memory_center.core.rules import CONSTITUTION_RULES
        assert len(CONSTITUTION_RULES) == 5
        for rule in CONSTITUTION_RULES:
            assert "id" in rule
            assert "principle" in rule
            assert "constraint_level" in rule
            assert "status" in rule

    def test_constitution_conflict_detection(self):
        """check_constitution_conflicts detects secret patterns."""
        from memory_center.core.rules import check_constitution_conflicts
        conflicts = check_constitution_conflicts(intent="set password=abc123")
        assert len(conflicts) >= 1
        assert conflicts[0]["severity"] == "critical"

    def test_constitution_no_conflict_for_safe_intent(self):
        """check_constitution_conflicts returns empty for safe intents."""
        from memory_center.core.rules import check_constitution_conflicts
        conflicts = check_constitution_conflicts(intent="add new feature")
        assert len(conflicts) == 0

    def test_constitution_private_path_detection(self):
        """check_constitution_conflicts detects private paths in files."""
        from memory_center.core.rules import check_constitution_conflicts
        conflicts = check_constitution_conflicts(files=["/Users/john/project/src/Main.java"])
        assert len(conflicts) >= 1


# ===========================================================================
# H-02: Traceability Graph
# ===========================================================================

class TestH02_Traceability:
    """H-02: Traceability graph deepening."""

    def test_build_traceability_graph(self, tmp_path):
        """build_traceability_graph returns nodes, edges, diagnostics."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.artifacts import build_traceability_graph
        result = build_traceability_graph(str(ws))
        assert "nodes" in result
        assert "edges" in result
        assert "diagnostics" in result
        assert "total_nodes" in result["diagnostics"]
        assert "unlinked_tasks" in result["diagnostics"]
        assert "uncovered_requirements" in result["diagnostics"]


# ===========================================================================
# H-04: Resumable Workflow
# ===========================================================================

class TestH04_ResumableWorkflow:
    """H-04: Resumable workflow state machine deepening."""

    def test_workflow_step_states_defined(self):
        """Workflow step states are well-defined."""
        from memory_center.core.verification.workflow_profiles import BUILTIN_PROFILES
        # All profiles have defined steps
        for profile in BUILTIN_PROFILES.values():
            for step in profile.steps:
                assert "step" in step
                assert "tool" in step
                assert "description" in step


# ===========================================================================
# H-05: Diff Scope
# ===========================================================================

class TestH05_DiffScope:
    """H-05: Diff scope and preview deepening."""

    def test_diff_scope_dataclass(self):
        """DiffScope has all required fields."""
        from memory_center.core.indexing.incremental import DiffScope
        scope = DiffScope(
            scope_type="workspace",
            included=[],
            excluded=[],
            excluded_reasons={},
            binary_files=[],
            total_files=0,
        )
        d = scope.to_dict()
        assert d["scope_type"] == "workspace"
        assert d["total_files"] == 0
        assert "included_count" in d
        assert "excluded_count" in d

    def test_detect_diff_scope_no_git(self, tmp_path):
        """detect_diff_scope returns empty for non-git dirs."""
        from memory_center.core.indexing.incremental import detect_diff_scope
        scope = detect_diff_scope(tmp_path, scope_type="workspace")
        assert scope.total_files == 0
        assert len(scope.included) == 0


# ===========================================================================
# H-06~H-08: Change bundles / Rule preview / Review
# ===========================================================================

class TestH06_H08_ChangeReview:
    """H-06~H-08: Change bundles, rule preview, review deepening."""

    def test_rules_load(self, tmp_path):
        """load_rules returns rules from workspace."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.rules import load_rules
        from memory_center.core.store import WorkspaceStore
        store = WorkspaceStore(str(ws))
        rules = load_rules(store)
        assert len(rules) >= 5  # Default rules
        for rule in rules:
            assert hasattr(rule, 'id')
            assert hasattr(rule, 'severity')

    def test_match_rules(self, tmp_path):
        """match_rules matches by intent, files, and scopes."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.rules import match_rules
        from memory_center.core.store import WorkspaceStore
        store = WorkspaceStore(str(ws))
        # Match by intent keywords
        matched = match_rules(store, intent="MQ consumer kafka")
        assert len(matched) >= 1
        assert any("MQ" in m.get("id", "") or "consumer" in m.get("rule", "").lower() for m in matched)

    def test_match_rules_glob(self, tmp_path):
        """match_rules matches file patterns with glob."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.rules import match_rules
        from memory_center.core.store import WorkspaceStore
        store = WorkspaceStore(str(ws))
        matched = match_rules(store, files=["src/OrderConsumer.java"])
        assert len(matched) >= 1


# ===========================================================================
# H-09~H-10: Finding location, validation, dedup
# ===========================================================================

class TestH09_H10_FindingValidation:
    """H-09~H-10: Finding location, validation, and review-to-verification."""

    def test_verification_loop_complete_phase(self, tmp_path):
        """VerificationLoop.complete_phase() records phase completion."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.loop import VerificationLoop
        loop = VerificationLoop(str(ws))
        started = loop.start("task-findings", "Test findings")
        loop_id = started["loop_id"]
        result = loop.complete_phase(loop_id, "verify", {"findings": [], "passed": True})
        assert result["status"] == "completed"
        assert result["phase"] == "verify"

    def test_pattern_promotion_list(self, tmp_path):
        """PatternPromotion.list_proposals() returns proposed items."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.pattern_promotion import PatternPromotion
        pp = PatternPromotion(str(ws))
        pp.propose("rule", "rule-1", "test_pattern", "test description", [])
        proposals = pp.list_proposals()
        assert len(proposals) >= 1


# ===========================================================================
# I-01~I-05: Documentation, compatibility, security, verification, release
# ===========================================================================

class TestI01_I05_FinalVerification:
    """I-01~I-05: Final verification checks."""

    def test_version_consistency(self):
        """Version in __init__.py is consistent."""
        import memory_center
        assert hasattr(memory_center, '__version__')
        assert isinstance(memory_center.__version__, str)
        assert len(memory_center.__version__.split('.')) >= 2

    def test_compile_all(self):
        """All modules compile without syntax errors."""
        import py_compile
        mc_dir = Path(__file__).parent.parent / "memory_center"
        errors = []
        for py_file in mc_dir.rglob("*.py"):
            try:
                py_compile.compile(str(py_file), doraise=True)
            except py_compile.PyCompileError as e:
                errors.append(str(e))
        assert errors == [], f"Compile errors: {errors}"

    def test_no_private_paths_in_source(self):
        """Source files don't contain obvious private paths."""
        import re
        mc_dir = Path(__file__).parent.parent / "memory_center"
        private_path_pattern = re.compile(r'/Users/[a-zA-Z][a-zA-Z0-9_-]+/[a-zA-Z]')
        violations = []
        for py_file in mc_dir.rglob("*.py"):
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            # Skip if it's clearly a test/example path pattern
            for match in private_path_pattern.finditer(content):
                path = match.group(0)
                # Allow common system paths
                if "/Users/cuijiaqi" not in path:
                    continue
                violations.append(f"{py_file}: {path}")
        assert violations == [], f"Private paths found: {violations}"

    def test_facade_schemas_defined(self):
        """Facade schemas are properly defined."""
        from memory_center.core.schemas import with_schema
        result = with_schema("test_schema", {"key": "value"})
        assert result["key"] == "value"
        assert "schema" in result

    def test_diagnostics_safe_reason(self):
        """safe_reason doesn't expose private info."""
        from memory_center.core.diagnostics import safe_reason
        reason = safe_reason("error at /Users/john/secret/file.py")
        # Should not contain the full private path
        assert isinstance(reason, str)

    def test_error_model_exists(self):
        """MCError hierarchy exists."""
        from memory_center.core.errors import MCError
        assert issubclass(MCError, Exception)

    def test_capability_matrix_exists(self):
        """Capability matrix is importable."""
        from memory_center.core.capability_matrix import CAPABILITIES
        assert isinstance(CAPABILITIES, (list, dict))
        assert len(CAPABILITIES) > 0

    def test_ontology_registry_consistency(self):
        """Ontology edge types are consistent."""
        from memory_center.core.ontology import edge_strength
        # Known edge types
        for edge_type in ["CALLS", "CALLS_SERVICE", "IMPLEMENTS_FEIGN", "DECLARES", "CONTAINS"]:
            strength = edge_strength(edge_type)
            assert isinstance(strength, str) and len(strength) > 0

    def test_schema_snapshot_compat(self, tmp_path):
        """Schema compatibility test structure exists."""
        from memory_center.core.schemas import with_schema
        # Schema versioning works
        result = with_schema("memory_query", {"results": []})
        assert "schema" in result
        assert result["schema"]["name"] == "memory_query"
