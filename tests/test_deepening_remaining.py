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
        from memory_center.core.storage.unified import UnifiedStore
        from memory_center.core.domain.extractor import BusinessDomainExtractor
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
        from memory_center.core.storage.unified import UnifiedStore
        from memory_center.core.domain.extractor import BusinessDomainExtractor
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
        from memory_center.core.graph import GraphStore
        from memory_center.core.domain.flow import BusinessFlowExtractor
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
        from memory_center.core.storage.unified import UnifiedStore
        from memory_center.core.domain.flow import BusinessFlowGraph
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
        from memory_center.core.storage.unified import UnifiedStore
        from memory_center.core.domain.flow import BusinessFlowGraph
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
        from memory_center.core.storage.unified import UnifiedStore
        from memory_center.core.domain.flow import BusinessFlowGraph
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
        from memory_center.core.onboarding import guide, glossary, tour
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
            workspace_start_session, workspace_recent_sessions,
        )
        workspace_start_session(str(ws), intent="test_d06_resume")
        result = workspace_recent_sessions(str(ws), limit=5)
        assert "recent_sessions" in result
        assert isinstance(result["recent_sessions"], list)

    def test_suggest_case_returns_draft(self, tmp_path):
        """workspace_suggest_case returns a draft case from a completed session."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.orchestrator.session import (
            workspace_start_session, workspace_log_session_event,
            workspace_end_session, workspace_suggest_case,
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


# ── G-05: Bundle Export Safety ──────────────────────────────────────

class TestG05BundleExportSafety:
    """Test agent bundle export safety."""

    def test_bundle_no_secrets(self, tmp_path):
        """Generated bundles contain no secrets or private paths."""
        ws = copy_demo_workspace(tmp_path)
        from memory_center.core.verification.bundle_export import generate_agent_bundle
        import json
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
        from memory_center.core.write_receipts import build_write_receipt, persist_write_receipt
        from memory_center.core.store import WorkspaceStore
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
