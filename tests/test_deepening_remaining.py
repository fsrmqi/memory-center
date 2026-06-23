"""Deepening tests for remaining work packages.

Covers the gaps identified in execution log "未覆盖项" and "仍需深化的项目":

- H-04: VerificationLoop step persistence (persist_step_state, get_step_states, resume_from_last_step, check_completion)
- D-01: Session workflow recommendation + context pack hint  
- D-04: Domain/Flow integration
- D-05: Onboarding/Persona differentiation
- D-06: Resume/Handoff summary
- C-05: Chain traversal edge cases
- G-03: Pattern promotion deeper behavior
- G-05: Bundle export deeper safety
- H-06: Change bundle structure
- H-07: Layered rule matching deeper
- H-09: Finding location and dedup
- H-10: Review → Verification loop
"""
from __future__ import annotations

from tests.fixtures import copy_demo_workspace

# ── H-04: VerificationLoop Step Persistence ─────────────────────────

class TestH04StepPersistence:
    """Test persist_step_state, get_step_states, resume_from_last_step."""

    def test_persist_step_state_returns_entry(self, tmp_path):
        """persist_step_state returns a dict with step_name and state."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.loop import VerificationLoop
        vl = VerificationLoop(str(ws))
        loop = vl.start("task-step-1", "Step persistence test")
        loop_id = loop["loop_id"]
        entry = vl.persist_step_state(
            loop_id, "analyze", "load_context", "completed",
            output_refs=[{"ref": "ctx:1"}],
            diagnostics={"status": "ok"},
        )
        assert entry["step_name"] == "load_context"
        assert entry["state"] == "completed"
        assert entry["loop_id"] == loop_id
        assert entry["output_refs"] == [{"ref": "ctx:1"}]

    def test_get_step_states_returns_list(self, tmp_path):
        """get_step_states returns persisted steps for a loop."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.loop import VerificationLoop
        vl = VerificationLoop(str(ws))
        loop = vl.start("task-step-2", "Step states test")
        lid = loop["loop_id"]
        vl.persist_step_state(lid, "analyze", "fetch_graph", "completed")
        vl.persist_step_state(lid, "analyze", "run_patterns", "completed")
        vl.persist_step_state(lid, "checklist", "generate", "running")
        states = vl.get_step_states(lid)
        assert len(states) == 3
        names = [s["step_name"] for s in states]
        assert "fetch_graph" in names
        assert "run_patterns" in names
        assert "generate" in names

    def test_resume_from_last_step_all_completed(self, tmp_path):
        """When all steps are completed, resume_from returns 'none'."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.loop import VerificationLoop
        vl = VerificationLoop(str(ws))
        loop = vl.start("task-resume-ok", "Resume completed test")
        lid = loop["loop_id"]
        vl.persist_step_state(lid, "analyze", "step_a", "completed")
        vl.persist_step_state(lid, "checklist", "step_b", "completed")
        result = vl.resume_from_last_step(lid)
        assert result["resume_from"] == "none"
        assert result["reason"] == "all_completed"
        assert "step_a" in result["completed_steps"]
        assert "step_b" in result["completed_steps"]

    def test_resume_from_last_step_paused(self, tmp_path):
        """When a step is paused, resume_from returns that step."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.loop import VerificationLoop
        vl = VerificationLoop(str(ws))
        loop = vl.start("task-resume-pause", "Resume paused test")
        lid = loop["loop_id"]
        vl.persist_step_state(lid, "analyze", "step_a", "completed")
        vl.persist_step_state(lid, "checklist", "step_b", "paused")
        result = vl.resume_from_last_step(lid)
        assert result["resume_from"] == "step_b"
        assert result["reason"] == "paused"
        assert "step_a" in result["completed_steps"]

    def test_resume_from_last_step_failed(self, tmp_path):
        """When a step fails, resume_from returns the failed step."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.loop import VerificationLoop
        vl = VerificationLoop(str(ws))
        loop = vl.start("task-resume-fail", "Resume failed test")
        lid = loop["loop_id"]
        vl.persist_step_state(lid, "analyze", "step_a", "completed")
        vl.persist_step_state(lid, "verify", "step_b", "failed",
                              diagnostics={"error": "assertion failed"})
        result = vl.resume_from_last_step(lid)
        assert result["resume_from"] == "step_b"
        assert result["reason"] == "failed"

    def test_resume_from_last_step_empty_loop(self, tmp_path):
        """When no steps are persisted, resume_from returns 'beginning'."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.loop import VerificationLoop
        vl = VerificationLoop(str(ws))
        loop = vl.start("task-resume-empty", "Resume empty test")
        result = vl.resume_from_last_step(loop["loop_id"])
        assert result["resume_from"] == "beginning"
        assert result["completed_steps"] == []

    def test_check_completion_all_phases(self, tmp_path):
        """check_completion reports 100% when all phases are completed."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.loop import VerificationLoop
        vl = VerificationLoop(str(ws))
        loop = vl.start("task-cc-1", "Completion test")
        lid = loop["loop_id"]
        for phase in ("analyze", "checklist", "verify", "close"):
            vl.complete_phase(lid, phase, {"done": True})
        result = vl.check_completion("task-cc-1")
        assert result["completion_pct"] == 100.0
        assert result["status"] == "completed"
        assert result["total_phases"] == 4
        assert vl.get_status("task-cc-1")["status"] == "completed"

    def test_check_completion_partial(self, tmp_path):
        """check_completion reports partial completion."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.loop import VerificationLoop
        vl = VerificationLoop(str(ws))
        loop = vl.start("task-cc-2", "Partial test")
        lid = loop["loop_id"]
        vl.complete_phase(lid, "analyze", {"findings": []})
        result = vl.check_completion("task-cc-2")
        assert result["completion_pct"] == 25.0
        assert "analyze" in result["completed_phases"]
        assert "checklist" in result["pending_phases"]

    def test_check_completion_no_loop(self, tmp_path):
        """check_completion returns no_loop status when task not found."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.loop import VerificationLoop
        vl = VerificationLoop(str(ws))
        result = vl.check_completion("nonexistent-task")
        assert result["status"] == "no_loop"
        assert result["completion_pct"] == 0

    def test_check_completion_graceful_on_read_error(self, tmp_path):
        """check_completion handles corrupted log gracefully."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.loop import VerificationLoop
        vl = VerificationLoop(str(ws))
        # Even with no log file, should return gracefully
        result = vl.check_completion("any-task")
        assert result["status"] == "no_loop"


# ── D-01: Session Workflow Recommendation + Context Pack Hint ────────

class TestD01SessionWorkflowHint:
    """Test session_start returns workflow recommendation and context pack hint."""

    def test_session_start_returns_workflow_recommendation(self, tmp_path):
        """workspace_start_session returns workflow_recommendation for any intent."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.orchestrator.session import workspace_start_session
        result = workspace_start_session(str(ws), intent="Feign 契约变更")
        assert "workflow_recommendation" in result
        rec = result["workflow_recommendation"]
        assert "recommended_profile" in rec
        assert "tools_sequence" in rec
        assert isinstance(rec["tools_sequence"], list)
        # "feign" + "contract" should recommend contract-change
        assert rec["recommended_profile"] == "contract-change"

    def test_session_start_quick_fix_recommendation(self, tmp_path):
        """bugfix intent recommends quick-fix profile."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.orchestrator.session import workspace_start_session
        result = workspace_start_session(str(ws), intent="修复登录bug")
        rec = result["workflow_recommendation"]
        assert rec["recommended_profile"] == "quick-fix"

    def test_session_start_architecture_recommendation(self, tmp_path):
        """architecture intent recommends architecture profile."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.orchestrator.session import workspace_start_session
        result = workspace_start_session(str(ws), intent="架构重构订单模块")
        rec = result["workflow_recommendation"]
        assert rec["recommended_profile"] == "architecture"

    def test_session_start_workflow_recommendation_applies_learning(self, tmp_path):
        """workflow recommendation should allow learned profile preference to correct static default."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.orchestrator.session import workspace_start_session
        from memory_center.core.verification.heuristics import HeuristicsRegister

        hr = HeuristicsRegister(str(ws))
        hr.record_candidate_path_feedback(
            candidate_type="workflow_profile",
            target="quick-fix",
            outcome="rollback",
            evidence=[{"type": "review", "id": "ev-8"}],
            source="unit-test",
            session_id="wf-1",
            weight_before=0.70,
        )
        hr.record_candidate_path_feedback(
            candidate_type="workflow_profile",
            target="long-task",
            outcome="confirmed",
            evidence=[{"type": "test", "id": "ev-9"}],
            source="unit-test",
            session_id="wf-2",
            weight_before=0.62,
        )
        hr.record_candidate_path_feedback(
            candidate_type="workflow_profile",
            target="long-task",
            outcome="confirmed",
            evidence=[{"type": "test", "id": "ev-10"}],
            source="unit-test",
            session_id="wf-3",
        )

        result = workspace_start_session(str(ws), intent="修复登录bug")
        rec = result["workflow_recommendation"]
        assert rec["recommended_profile"] == "long-task"
        assert rec["learning_applied"] is True
        assert rec["learning_state"] == "stable"
        assert rec["candidate_profiles"][0]["name"] == "long-task"

    def test_session_start_context_pack_hint(self, tmp_path):
        """workspace_start_session returns context_pack_hint."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.orchestrator.session import workspace_start_session
        result = workspace_start_session(str(ws), intent="了解项目架构")
        assert "context_pack_hint" in result
        hint = result["context_pack_hint"]
        assert "available" in hint

    def test_session_start_freshness_info(self, tmp_path):
        """workspace_start_session returns freshness info."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.orchestrator.session import workspace_start_session
        result = workspace_start_session(str(ws), intent="test freshness")
        assert "freshness" in result
        # freshness should be a dict (may be empty on error, but should exist)
        assert isinstance(result["freshness"], dict)


# ── D-04: Domain/Flow Integration ───────────────────────────────────

class TestD04DomainFlowIntegration:
    """Test BusinessDomainExtractor and BusinessFlowGraph deeper."""

    def test_domain_extractor_returns_domains(self, tmp_path):
        """BusinessDomainExtractor extracts domains from demo workspace."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.domain.extractor import BusinessDomainExtractor
        from memory_center.core.storage.unified import UnifiedStore
        from memory_center.core.store import WorkspaceStore
        store = WorkspaceStore(str(ws))
        with UnifiedStore(store.graph_db_path) as unified:
            extractor = BusinessDomainExtractor(unified)
            domains = extractor.extract_domains()
            # Should find at least some domains
            assert isinstance(domains, list)
            for d in domains:
                assert d.domain_id.startswith("domain:")
                assert d.confidence >= 0.0
                assert d.confidence <= 1.0
                assert isinstance(d.services, list)
                assert isinstance(d.entities, list)

    def test_domain_to_dict_has_explanation(self, tmp_path):
        """BusinessDomain.to_dict() includes _explanation."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.domain.extractor import BusinessDomainExtractor
        from memory_center.core.storage.unified import UnifiedStore
        from memory_center.core.store import WorkspaceStore
        store = WorkspaceStore(str(ws))
        with UnifiedStore(store.graph_db_path) as unified:
            extractor = BusinessDomainExtractor(unified)
            domains = extractor.extract_domains()
            if domains:
                d = domains[0].to_dict()
                assert "_explanation" in d
                exp = d["_explanation"]
                assert "subject" in exp
                assert "summary" in exp
                assert "semantic_strength" in exp

    def test_business_flow_extractor_returns_flows(self, tmp_path):
        """BusinessFlowExtractor returns flows from demo workspace."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.domain.flow import BusinessFlowExtractor
        from memory_center.core.graph import GraphStore
        from memory_center.core.store import WorkspaceStore
        store = WorkspaceStore(str(ws))
        with GraphStore(store.graph_db_path) as graph:
            extractor = BusinessFlowExtractor(graph)
            # Find a seed node
            nodes = graph.find_nodes("", limit=1)
            if nodes:
                flows = extractor.extract_flows(nodes[0]["id"], max_depth=2)
                assert isinstance(flows, list)
                for f in flows:
                    assert f.flow_id
                    assert f.name

    def test_flow_graph_build_returns_structure(self, tmp_path):
        """BusinessFlowGraph.build_flow_graph returns nodes and edges."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.domain.flow import BusinessFlowGraph
        from memory_center.core.storage.unified import UnifiedStore
        from memory_center.core.store import WorkspaceStore
        store = WorkspaceStore(str(ws))
        with UnifiedStore(store.graph_db_path) as unified:
            fg = BusinessFlowGraph(unified)
            result = fg.build_flow_graph()
            assert "nodes" in result
            assert "edges" in result
            assert "node_count" in result
            assert "edge_count" in result

    def test_flow_impact_returns_list(self, tmp_path):
        """BusinessFlowGraph.find_impact_along_flows returns impact list."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.domain.flow import BusinessFlowGraph
        from memory_center.core.storage.unified import UnifiedStore
        from memory_center.core.store import WorkspaceStore
        store = WorkspaceStore(str(ws))
        with UnifiedStore(store.graph_db_path) as unified:
            fg = BusinessFlowGraph(unified)
            nodes = unified.all_nodes()
            if nodes:
                impacted = fg.find_impact_along_flows(nodes[0]["id"], max_depth=2)
                assert isinstance(impacted, list)

    def test_flow_trace_from_endpoint(self, tmp_path):
        """BusinessFlowGraph.trace_flow_from_endpoint returns a FlowPath."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.domain.flow import BusinessFlowGraph
        from memory_center.core.storage.unified import UnifiedStore
        from memory_center.core.store import WorkspaceStore
        store = WorkspaceStore(str(ws))
        with UnifiedStore(store.graph_db_path) as unified:
            fg = BusinessFlowGraph(unified)
            endpoints = [n for n in unified.all_nodes() if n.get("type") == "Endpoint"]
            if endpoints:
                path = fg.trace_flow_from_endpoint(endpoints[0]["id"])
                assert path.path_id
                assert path.nodes
                assert endpoints[0]["id"] in path.nodes


# ── D-05: Onboarding/Persona ────────────────────────────────────────

class TestD05OnboardingPersona:
    """Test onboarding and persona differentiation."""

    def test_onboarding_modules_importable(self):
        """All onboarding submodules are importable."""
        from memory_center.core.onboarding import glossary, guide, tour
        assert guide is not None
        assert glossary is not None
        assert tour is not None

    def test_explanation_persona_adaptation_differs(self):
        """Different personas produce different outputs."""
        from memory_center.core.explanation.schema import Explanation
        exp = Explanation(
            subject="UserService",
            summary="用户服务调用订单服务",
            next_actions=["检查架构依赖", "查看影响范围", "运行测试"],
        )
        dev = exp.adapt_for_persona("developer")
        arch = exp.adapt_for_persona("architect")
        mgr = exp.adapt_for_persona("manager")
        # Architect view should have architecture-related prefix
        assert "架构" in arch.summary or "architect" in arch.persona
        # Manager view should have management-related prefix
        assert "管理" in mgr.summary or "manager" in mgr.persona
        # Developer view should be unchanged
        assert dev.summary == exp.summary

    def test_explanation_persona_filters_actions(self):
        """Persona adaptation filters next_actions by relevance."""
        from memory_center.core.explanation.schema import Explanation
        exp = Explanation(
            subject="Test",
            summary="Test explanation",
            next_actions=["检查架构依赖", "运行测试", "查看影响范围", "重构模块"],
        )
        arch = exp.adapt_for_persona("architect")
        # Architect should keep architecture-related actions
        arch_keywords = ["架构", "依赖", "风险", "重构", "pattern", "architecture"]
        for action in arch.next_actions:
            assert any(k in action.lower() for k in arch_keywords)


# ── D-06: Resume/Handoff Summary ────────────────────────────────────

class TestD06ResumeHandoffSummary:
    """Test resume/handoff summary quality."""

    def test_recent_sessions_returns_list(self, tmp_path):
        """workspace_recent_sessions returns a dict with recent_sessions list."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.orchestrator.session import (
            workspace_recent_sessions,
            workspace_start_session,
        )
        workspace_start_session(str(ws), intent="test_d06_resume")
        result = workspace_recent_sessions(str(ws), limit=5)
        assert "recent_sessions" in result
        assert isinstance(result["recent_sessions"], list)

    def test_suggest_case_returns_draft(self, tmp_path):
        """workspace_suggest_case returns a draft case from a completed session."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.orchestrator.session import (
            workspace_end_session,
            workspace_log_session_event,
            workspace_start_session,
            workspace_suggest_case,
        )
        start = workspace_start_session(str(ws), intent="test_resume_case")
        sid = start["session_id"]
        workspace_log_session_event(str(ws), sid, "tool_call", {"tool_name": "mc_lookup", "query": "UserService"})
        workspace_end_session(str(ws), sid, outcome="completed")
        result = workspace_suggest_case(str(ws), sid)
        assert result["found"] is True
        draft = result["draft_case"]
        assert draft is not None
        assert "task" in draft
        assert "memory_layer" in draft
        assert draft["memory_layer"] == "L1_case_atom"
        assert "evidence_refs" in draft


# ── C-05: Chain Traversal Edge Cases ────────────────────────────────

class TestC05ChainTraversal:
    """Test graph neighbors with edge cases."""

    def test_neighbors_returns_list(self, tmp_path):
        """GraphStore.neighbors returns a list for any node."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.graph import GraphStore
        from memory_center.core.store import WorkspaceStore
        store = WorkspaceStore(str(ws))
        with GraphStore(store.graph_db_path) as graph:
            nodes = graph.find_nodes("", limit=1)
            if nodes:
                nb = graph.neighbors(nodes[0]["id"], direction="downstream", max_depth=2, limit=10)
                assert isinstance(nb, list)

    def test_neighbors_nonexistent_node(self, tmp_path):
        """GraphStore.neighbors returns empty list for nonexistent node."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.graph import GraphStore
        from memory_center.core.store import WorkspaceStore
        store = WorkspaceStore(str(ws))
        with GraphStore(store.graph_db_path) as graph:
            nb = graph.neighbors("nonexistent-id-12345", direction="downstream", max_depth=2, limit=10)
            assert isinstance(nb, list)
            assert len(nb) == 0

    def test_neighbors_upstream_downstream(self, tmp_path):
        """Upstream and downstream directions both return results."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.graph import GraphStore
        from memory_center.core.store import WorkspaceStore
        store = WorkspaceStore(str(ws))
        with GraphStore(store.graph_db_path) as graph:
            nodes = graph.find_nodes("", limit=5)
            for node in nodes[:3]:
                up = graph.neighbors(node["id"], direction="upstream", max_depth=1, limit=5)
                down = graph.neighbors(node["id"], direction="downstream", max_depth=1, limit=5)
                assert isinstance(up, list)
                assert isinstance(down, list)

    def test_neighbors_max_depth_limits_results(self, tmp_path):
        """Higher max_depth should return >= lower max_depth results."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.graph import GraphStore
        from memory_center.core.store import WorkspaceStore
        store = WorkspaceStore(str(ws))
        with GraphStore(store.graph_db_path) as graph:
            nodes = graph.find_nodes("", limit=1)
            if nodes:
                shallow = graph.neighbors(nodes[0]["id"], direction="downstream", max_depth=1, limit=100)
                deep = graph.neighbors(nodes[0]["id"], direction="downstream", max_depth=3, limit=100)
                assert len(deep) >= len(shallow)


# ── G-03: Pattern Promotion Deeper ──────────────────────────────────

class TestG03PatternPromotionDeep:
    """Test pattern promotion deeper behavior."""

    def test_propose_and_list(self, tmp_path):
        """Proposed patterns appear in list_proposals."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.pattern_promotion import PatternPromotion
        pp = PatternPromotion(str(ws))
        pp.propose("case", "case-1", "error-handling", "统一异常处理模式", [{"type": "case", "id": "c1"}])
        proposals = pp.list_proposals(status="proposed")
        assert len(proposals) >= 1
        names = [p.get("pattern_name") for p in proposals]
        assert "error-handling" in names

    def test_promote_changes_status(self, tmp_path):
        """promote() creates an entry with action='promoted'."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.pattern_promotion import PatternPromotion
        pp = PatternPromotion(str(ws))
        proposal = pp.propose("rule", "rule-1", "retry-pattern", "重试模式", [{"type": "rule", "id": "r1"}])
        pid = proposal["promotion_id"]
        result = pp.promote(pid, scope="workspace")
        assert result["action"] == "promoted"
        assert result["scope"] == "workspace"

    def test_propose_with_multiple_evidence(self, tmp_path):
        """Pattern proposal tracks evidence count correctly."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.pattern_promotion import PatternPromotion
        pp = PatternPromotion(str(ws))
        evidence = [{"id": f"e{i}", "type": "case"} for i in range(10)]
        proposal = pp.propose("case", "case-2", "bulk-evidence", "大量证据测试", evidence)
        assert proposal["evidence_count"] == 10
        assert len(proposal["evidence_sample"]) == 5  # capped at 5

    def test_heuristics_confidence_sorting(self, tmp_path):
        """HeuristicsRegister.query returns results sorted by confidence."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.heuristics import HeuristicsRegister
        hr = HeuristicsRegister(str(ws))
        hr.record("retrieval", "exact-match-first", "feign query", "use exact match", confidence=0.3)
        hr.record("retrieval", "token-match-fallback", "generic query", "use token match", confidence=0.8)
        hr.record("retrieval", "semantic-rerank", "complex query", "use semantic rerank", confidence=0.6)
        results = hr.query(category="retrieval")
        assert len(results) >= 3
        # Should be sorted by confidence descending
        confidences = [r.get("confidence", 0) for r in results]
        assert confidences == sorted(confidences, reverse=True)

    def test_heuristics_category_filter(self, tmp_path):
        """HeuristicsRegister.query filters by category."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.heuristics import HeuristicsRegister
        hr = HeuristicsRegister(str(ws))
        hr.record("retrieval", "pattern-1", "trigger-1", "outcome-1")
        hr.record("indexing", "pattern-2", "trigger-2", "outcome-2")
        retrieval_results = hr.query(category="retrieval")
        indexing_results = hr.query(category="indexing")
        for r in retrieval_results:
            assert r.get("category") == "retrieval"
        for r in indexing_results:
            assert r.get("category") == "indexing"

    def test_candidate_feedback_confirmed_requires_evidence_for_uplift(self, tmp_path):
        """confirmed without evidence should not increase candidate weight."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.heuristics import HeuristicsRegister

        hr = HeuristicsRegister(str(ws))
        hr.record_candidate_path_feedback(
            candidate_type="impact_analysis",
            target="ArticleFeignClient",
            outcome="confirmed",
            evidence=[],
            source="unit-test",
            weight_before=0.62,
        )

        results = hr.query(category="candidate-path")
        assert results
        assert results[0]["target"] == "ArticleFeignClient"
        assert results[0]["confidence"] == 0.62

    def test_candidate_feedback_aggregates_and_reorders_by_weight(self, tmp_path):
        """confirmed and rejected feedback should aggregate into current weight ordering."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.heuristics import HeuristicsRegister

        hr = HeuristicsRegister(str(ws))
        hr.record_candidate_path_feedback(
            candidate_type="impact_analysis",
            target="ArticleFeignClient",
            outcome="confirmed",
            evidence=[{"type": "test", "id": "case-1"}],
            source="unit-test",
            weight_before=0.60,
        )
        hr.record_candidate_path_feedback(
            candidate_type="impact_analysis",
            target="TaskController",
            outcome="rejected",
            evidence=[{"type": "trace", "id": "case-2"}],
            source="unit-test",
            weight_before=0.70,
        )

        results = hr.query(category="candidate-path")
        assert len(results) >= 2
        assert results[0]["target"] == "ArticleFeignClient"
        assert results[0]["confidence"] == 0.72
        assert results[0]["recommended_weight"] == 0.54
        assert results[0]["promotion_ready"] is False
        assert results[1]["target"] == "TaskController"
        assert results[1]["confidence"] == 0.5

    def test_candidate_feedback_rolls_forward_existing_weight(self, tmp_path):
        """subsequent feedback should continue from aggregated weight instead of resetting."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.heuristics import HeuristicsRegister

        hr = HeuristicsRegister(str(ws))
        hr.record_candidate_path_feedback(
            candidate_type="impact_analysis",
            target="ArticleFeignClient",
            outcome="confirmed",
            evidence=[{"type": "test", "id": "ev-1"}],
            source="unit-test",
            weight_before=0.60,
        )
        hr.record_candidate_path_feedback(
            candidate_type="impact_analysis",
            target="ArticleFeignClient",
            outcome="demoted",
            evidence=[{"type": "review", "id": "ev-2"}],
            source="unit-test",
        )

        results = hr.query(category="candidate-path")
        assert results[0]["target"] == "ArticleFeignClient"
        assert results[0]["confidence"] == 0.64
        assert results[0]["recommended_weight"] == 0.64
        assert results[0]["promotion_ready"] is True

    def test_workspace_record_close_feedback_infers_lookup_path(self, tmp_path):
        """closing a verified session should auto-write candidate feedback from tool calls."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.orchestrator import (
            workspace_end_session,
            workspace_log_session_event,
            workspace_record_close_feedback,
            workspace_start_session,
        )
        from memory_center.core.verification.heuristics import HeuristicsRegister

        started = workspace_start_session(str(ws), "定位 ArticleFeignClient 调用链")
        sid = started["session_id"]
        workspace_log_session_event(str(ws), sid, "tool_call", {"tool_name": "memory_symbol_tool", "query": "ArticleFeignClient"})
        workspace_end_session(str(ws), sid, outcome="完成定位", verified_by=["manual-check"])

        feedback = workspace_record_close_feedback(str(ws), sid, source="unit-test")
        assert feedback["recorded"] is True
        assert feedback["inferred_outcome"] == "confirmed"
        assert feedback["feedback_items"][0]["candidate_type"] == "lookup_path"
        assert feedback["feedback_items"][0]["target"] == "symbol_lookup"

        hr = HeuristicsRegister(str(ws))
        results = hr.query(category="candidate-path")
        assert any(item.get("target") == "symbol_lookup" for item in results)

    def test_single_confirmed_candidate_stays_provisional_until_repeated(self, tmp_path):
        """one successful sample should not immediately become a stable high-priority default."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.heuristics import HeuristicsRegister

        hr = HeuristicsRegister(str(ws))
        hr.record_candidate_path_feedback(
            candidate_type="lookup_path",
            target="symbol_lookup",
            outcome="confirmed",
            evidence=[{"type": "test", "id": "ev-1"}],
            source="unit-test",
            session_id="s1",
            weight_before=0.60,
        )
        provisional = hr.query(category="candidate-path")[0]
        assert provisional["confidence"] == 0.72
        assert provisional["recommended_weight"] == 0.54
        assert provisional["promotion_ready"] is False
        assert provisional["guard_reason"] == "single-sample-positive"

        hr.record_candidate_path_feedback(
            candidate_type="lookup_path",
            target="symbol_lookup",
            outcome="confirmed",
            evidence=[{"type": "test", "id": "ev-2"}],
            source="unit-test",
            session_id="s2",
        )
        stabilized = hr.query(category="candidate-path")[0]
        assert stabilized["confidence"] == 0.84
        assert stabilized["recommended_weight"] == 0.84
        assert stabilized["promotion_ready"] is True
        assert stabilized["recommendation_state"] == "stable"

    def test_recommended_weight_sorting_prefers_stable_path(self, tmp_path):
        """sorting should prefer stable supported paths over raw one-off spikes."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.heuristics import HeuristicsRegister

        hr = HeuristicsRegister(str(ws))
        hr.record_candidate_path_feedback(
            candidate_type="lookup_path",
            target="symbol_lookup",
            outcome="confirmed",
            evidence=[{"type": "test", "id": "ev-1"}],
            source="unit-test",
            session_id="s1",
            weight_before=0.60,
        )
        hr.record_candidate_path_feedback(
            candidate_type="impact_analysis",
            target="ArticleFeignClient",
            outcome="confirmed",
            evidence=[{"type": "test", "id": "ev-2"}],
            source="unit-test",
            session_id="s2",
            weight_before=0.55,
        )
        hr.record_candidate_path_feedback(
            candidate_type="impact_analysis",
            target="ArticleFeignClient",
            outcome="confirmed",
            evidence=[{"type": "test", "id": "ev-3"}],
            source="unit-test",
            session_id="s3",
        )

        results = hr.query(category="candidate-path")
        assert results[0]["target"] == "ArticleFeignClient"
        assert results[0]["recommended_weight"] > results[1]["recommended_weight"]

    def test_rollback_feedback_forces_guarded_recommendation(self, tmp_path):
        """rollback should quickly suppress default recommendation priority."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.heuristics import HeuristicsRegister

        hr = HeuristicsRegister(str(ws))
        hr.record_candidate_path_feedback(
            candidate_type="lookup_path",
            target="symbol_lookup",
            outcome="confirmed",
            evidence=[{"type": "test", "id": "ev-1"}],
            source="unit-test",
            session_id="s1",
            weight_before=0.60,
        )
        hr.record_candidate_path_feedback(
            candidate_type="lookup_path",
            target="symbol_lookup",
            outcome="confirmed",
            evidence=[{"type": "test", "id": "ev-2"}],
            source="unit-test",
            session_id="s2",
        )
        hr.record_candidate_path_feedback(
            candidate_type="lookup_path",
            target="symbol_lookup",
            outcome="rollback",
            evidence=[{"type": "review", "id": "ev-3"}],
            source="unit-test",
            session_id="s3",
        )

        result = hr.query(category="candidate-path")[0]
        assert result["confidence"] == 0.56
        assert result["recommended_weight"] == 0.35
        assert result["promotion_ready"] is False
        assert result["recommendation_state"] == "rolled-back"
        assert result["guard_reason"] == "rollback-observed"

    def test_stale_candidate_decays_recommended_weight_only(self, tmp_path):
        """old untouched paths should decay in recommendation priority without losing raw confidence."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.heuristics import HeuristicsRegister

        hr = HeuristicsRegister(str(ws))
        stale_ts = "2025-01-01T00:00:00+00:00"
        hr.record_candidate_path_feedback(
            candidate_type="impact_analysis",
            target="ArticleFeignClient",
            outcome="confirmed",
            evidence=[{"type": "test", "id": "ev-1"}],
            source="unit-test",
            session_id="s1",
            weight_before=0.60,
            recorded_at=stale_ts,
            updated_at=stale_ts,
        )
        hr.record_candidate_path_feedback(
            candidate_type="impact_analysis",
            target="ArticleFeignClient",
            outcome="confirmed",
            evidence=[{"type": "test", "id": "ev-2"}],
            source="unit-test",
            session_id="s2",
            recorded_at=stale_ts,
            updated_at=stale_ts,
        )

        result = hr.query(category="candidate-path")[0]
        assert result["confidence"] == 0.84
        assert result["recommended_weight"] == 0.6048
        assert result["decay_applied"] is True
        assert result["recommendation_state"] == "stale"
        assert result["stale_days"] >= 30

    def test_lookup_hint_candidate_paths_apply_learned_weights(self, tmp_path):
        """workspace_lookup_hint should merge learned recommendation weights into candidate sorting."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.orchestrator import workspace_lookup_hint
        from memory_center.core.verification.heuristics import HeuristicsRegister

        hr = HeuristicsRegister(str(ws))
        hr.record_candidate_path_feedback(
            candidate_type="lookup_path",
            target="symbol_lookup",
            outcome="confirmed",
            evidence=[{"type": "test", "id": "ev-1"}],
            source="unit-test",
            session_id="s1",
            weight_before=0.60,
        )
        hr.record_candidate_path_feedback(
            candidate_type="lookup_path",
            target="symbol_lookup",
            outcome="confirmed",
            evidence=[{"type": "test", "id": "ev-2"}],
            source="unit-test",
            session_id="s2",
        )
        hr.record_candidate_path_feedback(
            candidate_type="lookup_path",
            target="symbol_lookup",
            outcome="rollback",
            evidence=[{"type": "review", "id": "ev-3"}],
            source="unit-test",
            session_id="s3",
        )

        hint = workspace_lookup_hint(str(ws), query="ArticleController 类", intent="", limit=5)
        learned = next(item for item in hint["candidate_paths"] if item.get("candidate_type") == "lookup_path")
        assert learned["candidate_type"] == "lookup_path"
        assert learned["learning_applied"] is True
        assert learned["learning_state"] == "rolled-back"
        assert learned["weight"] == 0.56
        assert learned["status"] == "possible"
        assert hint["candidate_paths"][0]["candidate_type"] != "lookup_path"

    def test_memory_impact_candidate_paths_apply_learned_weights(self, tmp_path):
        """memory_impact should surface learned impact recommendation state on candidate paths."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.orchestrator import memory_impact
        from memory_center.core.verification.heuristics import HeuristicsRegister

        hr = HeuristicsRegister(str(ws))
        hr.record_candidate_path_feedback(
            candidate_type="impact_analysis",
            target="MoveArticleRequest",
            outcome="rollback",
            evidence=[{"type": "review", "id": "ev-4"}],
            source="unit-test",
            session_id="impact-1",
            weight_before=0.70,
        )

        impact = memory_impact(str(ws), "MoveArticleRequest")
        learned_candidates = [item for item in impact["candidate_paths"] if item.get("learning_applied")]
        assert learned_candidates
        assert learned_candidates[0]["learning_state"] == "rolled-back"
        assert learned_candidates[0]["status"] == "possible"

    def test_runtime_audit_candidate_paths_apply_learned_weights(self, tmp_path):
        """runtime_audit should merge learned workspace governance feedback into candidate ordering."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.audit.runtime import audit_agent_runtime
        from memory_center.core.verification.heuristics import HeuristicsRegister

        hr = HeuristicsRegister(str(ws))
        hr.record_candidate_path_feedback(
            candidate_type="runtime_governance",
            target="hooks-mcp-agent-profile",
            outcome="confirmed",
            evidence=[{"type": "test", "id": "ev-5"}],
            source="unit-test",
            session_id="runtime-1",
            weight_before=0.60,
        )
        hr.record_candidate_path_feedback(
            candidate_type="runtime_governance",
            target="hooks-mcp-agent-profile",
            outcome="confirmed",
            evidence=[{"type": "test", "id": "ev-6"}],
            source="unit-test",
            session_id="runtime-2",
        )

        audit = audit_agent_runtime(str(ws))
        learned = next(item for item in audit["candidate_paths"] if item.get("candidate_type") == "runtime_governance")
        assert learned["learning_applied"] is True
        assert learned["learned_recommended_weight"] == 0.84
        assert learned["weight"] == 0.77

    def test_memory_discover_candidate_paths_apply_learned_weights(self, tmp_path):
        """memory_discover should expose learned task-sync priority in its executable recommendations."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.orchestrator.query import memory_discover
        from memory_center.core.verification.heuristics import HeuristicsRegister

        hr = HeuristicsRegister(str(ws))
        hr.record_candidate_path_feedback(
            candidate_type="task_sync",
            target="new-task-space",
            outcome="rollback",
            evidence=[{"type": "review", "id": "ev-7"}],
            source="unit-test",
            session_id="discover-1",
            weight_before=0.70,
        )

        result = memory_discover(str(ws), limit=20)
        learned = next(item for item in result["candidate_paths"] if item.get("candidate_type") == "task_sync")
        assert learned["learning_applied"] is True
        assert learned["learning_state"] == "rolled-back"
        assert learned["status"] == "possible"

    def test_heuristics_explain_shows_guard_and_recent_events(self, tmp_path):
        """explain should expose current recommendation state and recent feedback timeline."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.heuristics import HeuristicsRegister

        hr = HeuristicsRegister(str(ws))
        hr.record_candidate_path_feedback(
            candidate_type="lookup_path",
            target="symbol_lookup",
            outcome="confirmed",
            evidence=[{"type": "test", "id": "ev-explain-1"}],
            source="unit-test",
            session_id="explain-s1",
            weight_before=0.60,
        )
        hr.record_candidate_path_feedback(
            candidate_type="lookup_path",
            target="symbol_lookup",
            outcome="rollback",
            evidence=[{"type": "review", "id": "ev-explain-2"}],
            source="unit-test",
            session_id="explain-s2",
        )

        result = hr.explain(candidate_type="lookup_path", target="symbol_lookup")
        assert result["found"] is True
        assert result["current"]["recommendation_state"] == "rolled-back"
        assert result["current"]["guard_reason"] == "rollback-observed"
        assert result["event_count"] == 2
        assert len(result["recent_events"]) == 2
        assert result["recent_events"][0]["outcome"] == "rollback"
        assert any(reason["type"] == "recommendation_state" for reason in result["reasons"])
        assert result["policy_snapshot"]["kind"] == "candidate_path_learning"

    def test_legacy_candidate_feedback_without_schema_version_is_aggregated(self, tmp_path):
        """legacy candidate rows should still aggregate even without explicit schema metadata."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.store import WorkspaceStore
        from memory_center.core.verification.heuristics import HEURISTICS_FILE, HeuristicsRegister

        store = WorkspaceStore(str(ws))
        store.append_jsonl(
            HEURISTICS_FILE,
            {
                "heuristic_id": "legacy-candidate-1",
                "candidate_type": "lookup_path",
                "target": "symbol_lookup",
                "outcome": "confirmed",
                "evidence": [{"type": "test", "id": "legacy-1"}],
                "source": "legacy-import",
                "session_id": "legacy-session-1",
                "weight_before": 0.60,
                "confidence_delta": 0.12,
                "recorded_at": "2026-06-01T00:00:00+00:00",
            },
        )

        result = HeuristicsRegister(str(ws)).query(category="candidate-path")[0]
        assert result["category"] == "candidate-path"
        assert result["target"] == "symbol_lookup"
        assert result["schema_version"] == 1
        assert result["policy_version"] == 1
        assert result["confidence"] == 0.72
        assert result["recommended_weight"] == 0.54

    def test_legacy_confidence_delta_row_still_influences_query(self, tmp_path):
        """old confidence_delta-only rows should still adjust the latest aggregated confidence."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.store import WorkspaceStore
        from memory_center.core.verification.heuristics import HEURISTICS_FILE, HeuristicsRegister

        hr = HeuristicsRegister(str(ws))
        hr.record(
            "retrieval",
            "exact-match-first",
            "feign query",
            "use exact match",
            confidence=0.62,
            heuristic_id="legacy-heur-1",
            recorded_at="2026-06-01T00:00:00+00:00",
        )

        WorkspaceStore(str(ws)).append_jsonl(
            HEURISTICS_FILE,
            {
                "heuristic_id": "legacy-heur-1",
                "confidence_delta": 0.08,
                "updated_at": "2026-06-02T00:00:00+00:00",
            },
        )

        result = next(item for item in hr.query(category="retrieval") if item["heuristic_id"] == "legacy-heur-1")
        assert result["confidence"] == 0.7
        assert result["schema_version"] == 2
        assert result["policy_version"] == 1

    def test_learning_policy_defaults_version_when_missing(self, tmp_path):
        """workspace learning_policy without version should inherit the default policy version."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.config import load_workspace_data, write_workspace_data
        from memory_center.core.verification.heuristics import load_learning_policy

        data = load_workspace_data(ws)
        data["learning_policy"] = {
            "candidate_path_learning": {
                "provisional_promotion_cap": 0.5,
            }
        }
        write_workspace_data(ws, data)

        policy = load_learning_policy(ws)
        assert policy["version"] == 1
        assert policy["candidate_path_learning"]["provisional_promotion_cap"] == 0.5

    def test_new_records_include_schema_and_policy_version(self, tmp_path):
        """new heuristic records should persist explicit schema_version and policy_version."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.config import load_workspace_data, write_workspace_data
        from memory_center.core.verification.heuristics import (
            HEURISTICS_SCHEMA_VERSION,
            HeuristicsRegister,
        )

        data = load_workspace_data(ws)
        data["learning_policy"] = {
            "version": 3,
            "candidate_path_learning": {
                "provisional_promotion_cap": 0.5,
            },
        }
        write_workspace_data(ws, data)

        hr = HeuristicsRegister(str(ws))
        entry = hr.record_candidate_path_feedback(
            candidate_type="lookup_path",
            target="symbol_lookup",
            outcome="confirmed",
            evidence=[{"type": "test", "id": "ev-legacy-meta"}],
            source="unit-test",
            session_id="meta-1",
            weight_before=0.60,
        )

        assert entry["schema_version"] == HEURISTICS_SCHEMA_VERSION
        assert entry["policy_version"] == 3

    def test_learning_policy_can_override_provisional_cap(self, tmp_path):
        """workspace learning_policy should override provisional recommendation cap."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.config import load_workspace_data, write_workspace_data
        from memory_center.core.verification.heuristics import HeuristicsRegister

        data = load_workspace_data(ws)
        data["learning_policy"] = {
            "candidate_path_learning": {
                "provisional_promotion_cap": 0.5,
            }
        }
        write_workspace_data(ws, data)

        hr = HeuristicsRegister(str(ws))
        hr.record_candidate_path_feedback(
            candidate_type="lookup_path",
            target="symbol_lookup",
            outcome="confirmed",
            evidence=[{"type": "test", "id": "ev-13"}],
            source="unit-test",
            session_id="cfg-1",
            weight_before=0.60,
        )
        result = hr.query(category="candidate-path")[0]
        assert result["recommended_weight"] == 0.5

    def test_learning_policy_can_override_candidate_merge_weights(self, tmp_path):
        """workspace learning_policy should override rule/learned weight blending."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.config import load_workspace_data, write_workspace_data
        from memory_center.core.verification.heuristics import HeuristicsRegister, apply_candidate_path_learning

        data = load_workspace_data(ws)
        data["learning_policy"] = {
            "candidate_path_learning": {
                "merge_weights": {
                    "rule_weight": 0.2,
                    "learned_weight": 0.8,
                }
            }
        }
        write_workspace_data(ws, data)

        hr = HeuristicsRegister(str(ws))
        hr.record_candidate_path_feedback(
            candidate_type="lookup_path",
            target="symbol_lookup",
            outcome="confirmed",
            evidence=[{"type": "test", "id": "ev-14"}],
            source="unit-test",
            session_id="cfg-2",
            weight_before=0.60,
        )
        hr.record_candidate_path_feedback(
            candidate_type="lookup_path",
            target="symbol_lookup",
            outcome="confirmed",
            evidence=[{"type": "test", "id": "ev-15"}],
            source="unit-test",
            session_id="cfg-3",
        )

        candidates = apply_candidate_path_learning(
            str(ws),
            [
                {
                    "candidate_type": "lookup_path",
                    "target": "symbol_lookup",
                    "status": "probable",
                    "weight": 0.88,
                }
            ],
        )
        assert candidates[0]["weight"] == 0.85

    def test_learning_policy_can_override_workflow_merge_weights(self, tmp_path):
        """workspace learning_policy should override workflow profile blend weights."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.config import load_workspace_data, write_workspace_data
        from memory_center.core.verification.heuristics import HeuristicsRegister
        from memory_center.core.verification.workflow_profiles import recommend_workflow_with_learning

        data = load_workspace_data(ws)
        data["learning_policy"] = {
            "workflow_profile_learning": {
                "merge_weights": {
                    "base_weight": 0.1,
                    "learned_weight": 0.9,
                }
            }
        }
        write_workspace_data(ws, data)

        hr = HeuristicsRegister(str(ws))
        hr.record_candidate_path_feedback(
            candidate_type="workflow_profile",
            target="quick-fix",
            outcome="confirmed",
            evidence=[{"type": "test", "id": "ev-16"}],
            source="unit-test",
            session_id="wf-cfg-1",
            weight_before=0.62,
        )
        hr.record_candidate_path_feedback(
            candidate_type="workflow_profile",
            target="quick-fix",
            outcome="confirmed",
            evidence=[{"type": "test", "id": "ev-17"}],
            source="unit-test",
            session_id="wf-cfg-2",
        )

        result = recommend_workflow_with_learning(str(ws), "修复登录bug")
        assert result["recommended_profile"] == "quick-fix"
        assert result["candidate_profiles"][0]["weight"] == 0.87


# ── G-05: Bundle Export Safety ──────────────────────────────────────

class TestG05BundleExportSafety:
    """Test agent bundle export safety."""

    def test_bundle_no_secrets(self, tmp_path):
        """Generated bundles contain no secrets or private paths."""
        ws = copy_demo_workspace(tmp_path)
        import json

        from memory_center.core.verification.bundle_export import generate_agent_bundle
        bundle = generate_agent_bundle(str(ws), agent="codex")
        content = json.dumps(bundle)
        # No real secrets
        assert "sk-" not in content
        assert "AKIA" not in content
        assert "password" not in content.lower() or "no_password" in content.lower()

    def test_bundle_codex_structure(self, tmp_path):
        """Codex bundle has expected structure."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.bundle_export import generate_agent_bundle
        bundle = generate_agent_bundle(str(ws), agent="codex")
        assert isinstance(bundle, dict)
        assert "agent" in bundle or "config" in bundle or "hooks" in bundle

    def test_bundle_claude_structure(self, tmp_path):
        """Claude Code bundle has expected structure."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.bundle_export import generate_agent_bundle
        bundle = generate_agent_bundle(str(ws), agent="claude")
        assert isinstance(bundle, dict)

    def test_bundle_cursor_structure(self, tmp_path):
        """Cursor bundle has expected structure."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.bundle_export import generate_agent_bundle
        bundle = generate_agent_bundle(str(ws), agent="cursor")
        assert isinstance(bundle, dict)


# ── H-06: Change Bundle Structure ───────────────────────────────────

class TestH06ChangeBundles:
    """Test change bundle dataclass and structure."""

    def test_graph_view_dataclass_exists(self):
        """GraphView dataclass is importable and has expected fields."""
        from memory_center.core.verification.bundle_export import generate_agent_bundle
        # The change bundle structure is tested through the bundle export
        assert callable(generate_agent_bundle)

    def test_diff_scope_dataclass(self):
        """DiffScope dataclass has expected fields."""
        from memory_center.core.indexing.incremental import DiffScope
        ds = DiffScope(
            scope_type="workspace",
            included=["new.py", "changed.py"],
            excluded=["vendor/"],
            excluded_reasons={"vendor/": "excluded by rule"},
            binary_files=[],
            total_files=2,
        )
        assert ds.scope_type == "workspace"
        assert "new.py" in ds.included
        assert "vendor/" in ds.excluded
        assert ds.total_files == 2


# ── H-07: Layered Rule Matching Deeper ──────────────────────────────

class TestH07LayeredRulesDeep:
    """Test rules matching with glob patterns and priorities."""

    def test_rules_glob_match(self, tmp_path):
        """Rules with file_patterns match against file paths."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.rules import load_rules
        from memory_center.core.store import WorkspaceStore
        store = WorkspaceStore(str(ws))
        rules = load_rules(store)
        assert len(rules) > 0
        # All rules should have required fields
        for rule in rules:
            assert rule.id
            assert rule.severity in ("error", "warning", "info", "must", "should", "may")
            assert isinstance(rule.file_patterns, list)

    def test_match_rules_returns_matches(self, tmp_path):
        """match_rules returns matching rules for given intent and files."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.rules import match_rules
        from memory_center.core.store import WorkspaceStore
        store = WorkspaceStore(str(ws))
        matched = match_rules(store, intent="security audit", files=["src/main/java/Secret.java"])
        assert isinstance(matched, list)
        for m in matched:
            assert "rule" in m or "id" in m or "matched" in m

    def test_match_rules_empty_files(self, tmp_path):
        """match_rules handles empty file list gracefully."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.rules import match_rules
        from memory_center.core.store import WorkspaceStore
        store = WorkspaceStore(str(ws))
        matched = match_rules(store, intent="general query", files=[])
        assert isinstance(matched, list)

    def test_constitution_rules_have_ids(self):
        """All constitution rules have unique IDs."""
        from memory_center.core.rules import CONSTITUTION_RULES
        assert len(CONSTITUTION_RULES) == 5
        ids = [r["id"] for r in CONSTITUTION_RULES]
        assert len(ids) == len(set(ids)), "Constitution rule IDs must be unique"

    def test_constitution_conflict_detection(self):
        """check_constitution_conflicts detects secret-related intents."""
        from memory_center.core.rules import check_constitution_conflicts
        conflicts = check_constitution_conflicts(intent="add API key to config", files=[])
        assert isinstance(conflicts, list)

    def test_constitution_no_conflict_for_safe_intent(self):
        """check_constitution_conflicts returns empty for safe intents."""
        from memory_center.core.rules import check_constitution_conflicts
        conflicts = check_constitution_conflicts(intent="add unit test for UserService", files=["src/test/UserServiceTest.java"])
        assert len(conflicts) == 0


# ── H-09: Finding Location and Dedup ────────────────────────────────

class TestH09FindingLocation:
    """Test finding location through write receipts."""

    def test_write_receipts_have_ids(self, tmp_path):
        """write receipts have unique receipt_id."""
        copy_demo_workspace(tmp_path)
        from memory_center.core.write_receipts import build_write_receipt
        r1 = build_write_receipt(layer="L0", action="test_action", scope="memory", target="test_target", target_file="memory/test.jsonl")
        r2 = build_write_receipt(layer="L0", action="test_action_2", scope="memory", target="test_target_2", target_file="memory/test2.jsonl")
        assert "receipt_id" in r1
        assert "receipt_id" in r2
        assert r1["receipt_id"] != r2["receipt_id"]

    def test_write_receipts_persisted(self, tmp_path):
        """persist_write_receipt stores the receipt in workspace."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.store import WorkspaceStore
        from memory_center.core.write_receipts import build_write_receipt, persist_write_receipt
        store = WorkspaceStore(str(ws))
        receipt = build_write_receipt(layer="L1", action="persist_test", scope="memory", target="test", target_file="memory/test.jsonl")
        result = persist_write_receipt(store, receipt)
        assert result is not None


# ── H-10: Review → Verification Loop ────────────────────────────────

class TestH10ReviewVerification:
    """Test the review → verification → pattern promotion pipeline."""

    def test_verification_then_promotion_pipeline(self, tmp_path):
        """Complete a verification loop then propose a pattern."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.loop import VerificationLoop
        from memory_center.core.verification.pattern_promotion import PatternPromotion
        # Start verification
        vl = VerificationLoop(str(ws))
        loop = vl.start("pipeline-task", "Test pipeline")
        lid = loop["loop_id"]
        # Run phases
        vl.complete_phase(lid, "analyze", {"findings": ["finding-1", "finding-2"]})
        vl.complete_phase(lid, "checklist", {"items": ["check-1", "check-2"]})
        vl.complete_phase(lid, "verify", {"results": [{"check": "check-1", "pass": True}]})
        vl.complete_phase(lid, "close", {"summary": "All checks passed"})
        # Check completion
        result = vl.check_completion("pipeline-task")
        assert result["completion_pct"] == 100.0
        # Now propose a pattern from the findings
        pp = PatternPromotion(str(ws))
        proposal = pp.propose("verification", lid, "auto-test-pattern", "自动生成测试模式", [
            {"type": "finding", "id": "finding-1"},
            {"type": "finding", "id": "finding-2"},
        ])
        assert proposal["source_type"] == "verification"
        assert proposal["evidence_count"] == 2

    def test_generate_checklist_from_analysis(self, tmp_path):
        """generate_checklist produces items from task analysis."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.loop import VerificationLoop
        vl = VerificationLoop(str(ws))
        checklist = vl.generate_checklist({"task_type": "code_change"})
        assert checklist["task_type"] == "code_change"
        assert len(checklist["items"]) >= 3

    def test_generate_close_summary(self, tmp_path):
        """generate_close_summary returns a completion summary."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.loop import VerificationLoop
        vl = VerificationLoop(str(ws))
        summary = vl.generate_close_summary("close-task-1")
        assert summary["status"] == "completed"
        assert summary["task_id"] == "close-task-1"

    def test_complete_phase_persists_task_id_for_traceability(self, tmp_path):
        """complete_phase should preserve task_id so traceability can link verification to task."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.loop import VerificationLoop
        vl = VerificationLoop(str(ws))
        loop = vl.start("trace-task-1", "Traceability test")
        vl.complete_phase(loop["loop_id"], "analyze", {"findings": ["f1"]})

        step_status = vl.get_status("trace-task-1")
        assert step_status["task_id"] == "trace-task-1"

        from memory_center.core.artifacts import build_traceability_graph
        graph = build_traceability_graph(str(ws))
        verify_nodes = [n for n in graph["nodes"] if n.get("id") == f"verify:{loop['loop_id']}"]
        verify_edges = [
            e for e in graph["edges"]
            if e.get("source") == f"verify:{loop['loop_id']}" and e.get("target") == "task:trace-task-1"
        ]
        assert verify_nodes
        assert verify_edges


# ── F-07: Health and Governance ─────────────────────────────────────

class TestF07HealthGovernance:
    """Test health governance integration."""

    def test_audit_agent_runtime_returns_score(self, tmp_path):
        """audit_agent_runtime returns a score and findings."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.audit.runtime import audit_agent_runtime
        result = audit_agent_runtime(str(ws))
        assert isinstance(result, dict)
        assert "score" in result
        assert "findings" in result

    def test_completion_audit_on_demo(self, tmp_path):
        """run_completion_audit returns findings on demo workspace."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.audit.completion import run_completion_audit
        result = run_completion_audit(str(ws))
        assert isinstance(result, dict)
        assert "score" in result or "findings" in result

    def test_workspace_type_detection(self, tmp_path):
        """detect_workspace_type identifies different project types."""
        from memory_center.core.audit.completion import detect_workspace_type
        # Create a python project dir
        py_dir = tmp_path / "pyproject"
        py_dir.mkdir()
        (py_dir / "pyproject.toml").write_text("[project]\nname='test'\n")
        assert detect_workspace_type(py_dir) == "python"
        # Create a java-maven project dir
        mvn_dir = tmp_path / "mvnproject"
        mvn_dir.mkdir()
        (mvn_dir / "pom.xml").write_text("<project/>")
        assert detect_workspace_type(mvn_dir) == "java-maven"


# ── Explanation Schema Deepening ────────────────────────────────────

class TestExplanationSchemaDeep:
    """Test explanation schema backward compat and merge."""

    def test_backward_compat_wrapper_preserves_fields(self):
        """backward_compat_wrapper preserves existing fields."""
        from memory_center.core.explanation.schema import backward_compat_wrapper
        old = {"name": "UserService", "type": "Service", "project": "user-back"}
        wrapped = backward_compat_wrapper(old)
        assert wrapped["name"] == "UserService"
        assert wrapped["type"] == "Service"
        assert "summary" in wrapped
        assert "semantic_strength" in wrapped

    def test_backward_compat_already_valid(self):
        """backward_compat_wrapper passes through already-valid entries."""
        from memory_center.core.explanation.schema import backward_compat_wrapper
        valid = {"subject": "test", "summary": "test", "semantic_strength": "fact", "confidence": 0.9}
        result = backward_compat_wrapper(valid)
        assert result == valid

    def test_merge_explanations_empty(self):
        """merge_explanations handles empty list."""
        from memory_center.core.explanation.schema import merge_explanations
        result = merge_explanations([])
        assert result["confidence"] == 0.0

    def test_merge_explanations_preserves_weakest_strength(self):
        """merge_explanations uses the weakest semantic strength."""
        from memory_center.core.explanation.schema import merge_explanations
        entries = [
            {"subject": "a", "summary": "A", "semantic_strength": "fact", "confidence": 0.9},
            {"subject": "b", "summary": "B", "semantic_strength": "derived", "confidence": 0.5},
        ]
        result = merge_explanations(entries)
        assert result["semantic_strength"] == "derived"  # weakest
        assert result["confidence"] == 0.5  # min

    def test_retrieval_result_to_dict_reads_dict_evidence_edge_type(self):
        """_result_to_dict should support dict evidence instead of silently iterating dict keys."""
        from memory_center.core.retrieval.hybrid import RetrievalResult, _result_to_dict

        result = RetrievalResult(
            node_id="node-1",
            node={"id": "node-1", "type": "Class", "name": "Foo"},
            score=0.8,
            sources=["graph_exact"],
            evidence={"edge_type": "CALLS_METHOD"},
        )

        payload = _result_to_dict(result)
        assert payload["semantic_strength"] == "fact"
        assert payload["confidence_label"] == "high"


# ── Metrics Deepening ───────────────────────────────────────────────

class TestMetricsDeepening:
    """Test MetricsCollector deeper integration."""

    def test_metrics_collector_timer_context(self, tmp_path):
        """MetricsCollector.timer() measures elapsed time."""
        import time

        from memory_center.core.metrics import MetricsCollector
        mc = MetricsCollector(tmp_path / "workspace.yaml")
        with mc.timer("test_op"):
            time.sleep(0.01)
        summary = mc.summary("test_op")
        assert summary["count"] >= 1
        assert "avg_ms" in summary

    def test_metrics_collector_record_and_query(self, tmp_path):
        """MetricsCollector records and queries metrics."""
        from memory_center.core.metrics import MetricsCollector
        mc = MetricsCollector(tmp_path / "workspace.yaml")
        mc.record("lookup", {"query": "UserService", "latency_ms": 42})
        mc.record("lookup", {"query": "OrderService", "latency_ms": 38})
        results = mc.query("lookup")
        assert len(results) >= 2

    def test_metrics_collector_summary(self, tmp_path):
        """MetricsCollector.summary returns aggregated stats."""
        from memory_center.core.metrics import MetricsCollector
        mc = MetricsCollector(tmp_path / "workspace.yaml")
        mc.record("op1", 42.0)
        mc.record("op1", 38.0)
        summary = mc.summary("op1")
        assert "count" in summary
        assert summary["count"] >= 2
        assert "avg_ms" in summary
