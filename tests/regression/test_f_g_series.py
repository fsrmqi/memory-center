"""Tests for F-02 through F-07 and G-01 through G-07: Backend, Metrics, Governance, Runtime.

F-02: Backend migration consistency protection
F-03: Metrics system
F-04: Benchmark long-term trending
F-05: Regression alerts
F-06: Runtime audit productization
F-07: Health & governance loop
G-01: Workflow Protocol Profiles
G-02: Verification Loop strengthening
G-03: Pattern Promotion & Learned Heuristics
G-04: Agent Runtime Audit
G-05: Agent Usage Bundle Export
G-06: HTTP Workbench alignment
G-07: Install & build flow
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest


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


# ═════════════════════════════════════════════════════════════════════════════
# F-02: Backend Migration Consistency Protection
# ═════════════════════════════════════════════════════════════════════════════

class TestF02BackendConsistency:
    def test_unified_backend_query_class_exists(self):
        from memory_center.core.backend.query import UnifiedBackendQuery
        assert UnifiedBackendQuery is not None

    def test_unified_backend_query_reads_indexes(self, demo_workspace: Path):
        from memory_center.core.backend.query import UnifiedBackendQuery
        from memory_center.core.storage.workspace import WorkspaceStore
        ws = WorkspaceStore(str(demo_workspace))
        db_path = ws.runtime_db_path
        with UnifiedBackendQuery(db_path) as ubq:
            idx = ubq.read_index_list("file-index.json")
            assert isinstance(idx, list)

    def test_backend_query_records(self, demo_workspace: Path):
        from memory_center.core.backend.query import UnifiedBackendQuery
        from memory_center.core.storage.workspace import WorkspaceStore
        ws = WorkspaceStore(str(demo_workspace))
        db_path = ws.runtime_db_path
        with UnifiedBackendQuery(db_path) as ubq:
            result = ubq.query_records(limit=5)
            assert isinstance(result, dict)

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_backend_consistency_cli_entry(self, demo_workspace: Path):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


# ═════════════════════════════════════════════════════════════════════════════
# F-03: Metrics System
# ═════════════════════════════════════════════════════════════════════════════

class TestF03Metrics:
    def test_metrics_collector_class(self):
        from memory_center.core.observability.metrics import MetricsCollector
        assert MetricsCollector is not None

    def test_metrics_record_and_query(self, tmp_path: Path):
        from memory_center.core.observability.metrics import MetricsCollector
        ws_file = tmp_path / ".memory-center" / "workspace.yaml"
        ws_file.parent.mkdir(parents=True, exist_ok=True)
        ws_file.write_text("root: /tmp/test\n")
        mc = MetricsCollector(str(ws_file))
        mc.record("test_metric", 42.0, unit="ms")
        rows = mc.query("test_metric")
        assert len(rows) == 1
        assert rows[0]["value"] == 42.0

    def test_metrics_timer(self, tmp_path: Path):
        from memory_center.core.observability.metrics import MetricsCollector
        ws_file = tmp_path / ".memory-center" / "workspace.yaml"
        ws_file.parent.mkdir(parents=True, exist_ok=True)
        ws_file.write_text("root: /tmp/test\n")
        mc = MetricsCollector(str(ws_file))
        with mc.timer("test_timer"):
            pass  # should record elapsed time
        rows = mc.query("test_timer")
        assert len(rows) >= 1

    def test_metrics_summary(self, tmp_path: Path):
        from memory_center.core.observability.metrics import MetricsCollector
        ws_file = tmp_path / ".memory-center" / "workspace.yaml"
        ws_file.parent.mkdir(parents=True, exist_ok=True)
        ws_file.write_text("root: /tmp/test\n")
        mc = MetricsCollector(str(ws_file))
        for i in range(5):
            mc.record("perf", float(i * 10), unit="ms")
        summary = mc.summary("perf")
        assert summary["count"] == 5
        assert "avg_ms" in summary
        assert "p95_ms" in summary


# ═════════════════════════════════════════════════════════════════════════════
# F-04: Benchmark Long-term Trending
# ═════════════════════════════════════════════════════════════════════════════

class TestF04BenchmarkTrending:
    def test_record_baseline(self, demo_workspace: Path):
        from memory_center.core.benchmark.trending import record_benchmark_baseline
        result = record_benchmark_baseline(str(demo_workspace), "test_fn", 100, 60)
        assert result["recorded"] is True
        assert result["savings_pct"] == 40.0

    def test_record_trend(self, demo_workspace: Path):
        from memory_center.core.benchmark.trending import record_benchmark_trend
        result = record_benchmark_trend(str(demo_workspace), "test_fn", 200, 150)
        assert result["recorded"] is True

    def test_check_regression_alerts(self, demo_workspace: Path):
        from memory_center.core.benchmark.trending import check_regression_alerts
        
        result = check_regression_alerts(str(demo_workspace), threshold_pct=10.0)
        assert isinstance(result, dict)
        assert "alerts" in result
        result["alerts"]
        

    def test_regression_threshold_config(self):
        from memory_center.core.benchmark.trending import RegressionThresholdConfig
        config = RegressionThresholdConfig()
        assert config.default_threshold_pct > 0

    def test_check_regression_alerts_configurable(self, demo_workspace: Path):
        from memory_center.core.benchmark.trending import (
            RegressionThresholdConfig,
            check_regression_alerts_configurable,
        )
        config = RegressionThresholdConfig(default_threshold_pct=5.0)
        
        result2 = check_regression_alerts_configurable(str(demo_workspace), config)
        assert isinstance(result2, dict)
        result2.get("alerts", [])
        


# ═════════════════════════════════════════════════════════════════════════════
# F-05: Regression Alerts
# ═════════════════════════════════════════════════════════════════════════════

class TestF05RegressionAlerts:
    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_regression_alerts_cli(self, demo_workspace: Path):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_regression_alerts_http(self, demo_workspace: Path):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


# ═════════════════════════════════════════════════════════════════════════════
# F-06: Runtime Audit Productization
# ═════════════════════════════════════════════════════════════════════════════

class TestF06RuntimeAudit:
    def test_completion_audit_exists(self):
        from memory_center.core.audit.reports import run_completion_audit
        assert callable(run_completion_audit)

    def test_completion_audit_on_demo(self, demo_workspace: Path):
        from memory_center.core.audit.reports import run_completion_audit
        result = run_completion_audit(str(demo_workspace))
        assert isinstance(result, dict)
        assert "score" in result

    def test_workspace_type_detection(self):
        from memory_center.core.audit.reports import detect_workspace_type
        assert callable(detect_workspace_type)

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_audit_cli_entry(self, demo_workspace: Path):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


# ═════════════════════════════════════════════════════════════════════════════
# F-07: Health & Governance Loop
# ═════════════════════════════════════════════════════════════════════════════

class TestF07HealthGovernance:
    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_work_health_cli(self, demo_workspace: Path):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_work_health_http(self, demo_workspace: Path):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


# ═════════════════════════════════════════════════════════════════════════════
# G-01: Workflow Protocol Profiles
# ═════════════════════════════════════════════════════════════════════════════

class TestG01WorkflowProfiles:
    def test_builtin_profiles_exist(self):
        from memory_center.core.verification.workflow_profiles import BUILTIN_PROFILES
        assert "quick-fix" in BUILTIN_PROFILES
        assert "contract-change" in BUILTIN_PROFILES
        assert "long-task" in BUILTIN_PROFILES
        assert "architecture" in BUILTIN_PROFILES

    def test_get_workflow_profile(self):
        from memory_center.core.verification.workflow_profiles import get_workflow_profile
        profile = get_workflow_profile("quick-fix")
        assert profile is not None
        assert profile.name == "quick-fix"
        assert len(profile.steps) > 0
        assert len(profile.tools_sequence) > 0

    def test_recommend_workflow(self):
        from memory_center.core.verification.workflow_profiles import recommend_workflow
        profile = recommend_workflow("fix a bug in UserService")
        assert profile.name == "quick-fix"
        profile2 = recommend_workflow("refactor the feign client contract")
        assert profile2.name == "contract-change"

    def test_recommend_workflow_contract_change_overrides_generic_bugfix(self):
        from memory_center.core.verification.workflow_profiles import recommend_workflow

        profile = recommend_workflow("修复 Feign 接口返回字段兼容问题")
        assert profile.name == "contract-change"

    def test_recommend_workflow_with_learning(self, demo_workspace: Path):
        from memory_center.core.verification.heuristics import HeuristicsRegister
        from memory_center.core.verification.workflow_profiles import recommend_workflow_with_learning

        hr = HeuristicsRegister(str(demo_workspace))
        hr.record_candidate_path_feedback(
            candidate_type="workflow_profile",
            target="contract-change",
            outcome="confirmed",
            evidence=[{"type": "test", "id": "ev-11"}],
            source="unit-test",
            session_id="wf-a",
            weight_before=0.60,
        )
        hr.record_candidate_path_feedback(
            candidate_type="workflow_profile",
            target="contract-change",
            outcome="confirmed",
            evidence=[{"type": "test", "id": "ev-12"}],
            source="unit-test",
            session_id="wf-b",
        )

        result = recommend_workflow_with_learning(str(demo_workspace), "refactor the feign client contract")
        assert result["recommended_profile"] == "contract-change"
        assert result["candidate_profiles"][0]["name"] == "contract-change"

    def test_recommend_workflow_with_learning_keeps_candidate_status_consistent(self, demo_workspace: Path):
        from memory_center.core.verification.workflow_profiles import recommend_workflow_with_learning

        result = recommend_workflow_with_learning(str(demo_workspace), "修复 Feign 接口返回字段兼容问题")
        assert result["recommended_profile"] == "contract-change"
        assert result["candidate_profiles"][0]["name"] == "contract-change"
        assert result["candidate_profiles"][0]["status"] == "probable"
        assert all(item["status"] == "possible" for item in result["candidate_profiles"][1:])

    def test_rolled_back_workflow_profile_is_not_recommended(self, demo_workspace: Path):
        from memory_center.core.verification.heuristics import HeuristicsRegister
        from memory_center.core.verification.workflow_profiles import recommend_workflow_with_learning

        HeuristicsRegister(str(demo_workspace)).record_candidate_path_feedback(
            candidate_type="workflow_profile",
            target="quick-fix",
            outcome="rollback",
            evidence=[{"type": "review", "id": "workflow-rollback"}],
            source="unit-test",
            session_id="workflow-rollback",
            weight_before=0.99,
        )

        result = recommend_workflow_with_learning(str(demo_workspace), "修复登录 bug")
        assert result["recommended_profile"] == "long-task"
        rolled_back = next(item for item in result["candidate_profiles"] if item["name"] == "quick-fix")
        assert rolled_back["learning_state"] == "rolled-back"
        assert rolled_back["status"] == "possible"

    def test_all_rolled_back_workflow_profiles_withhold_recommendation(self, demo_workspace: Path):
        from memory_center.core.verification.heuristics import HeuristicsRegister
        from memory_center.core.verification.workflow_profiles import BUILTIN_PROFILES, recommend_workflow_with_learning

        register = HeuristicsRegister(str(demo_workspace))
        for index, profile_name in enumerate(BUILTIN_PROFILES):
            register.record_candidate_path_feedback(
                candidate_type="workflow_profile",
                target=profile_name,
                outcome="rollback",
                evidence=[{"type": "review", "id": f"workflow-withhold-{index}"}],
                source="unit-test",
                session_id=f"workflow-withhold-{index}",
                weight_before=0.99,
            )

        result = recommend_workflow_with_learning(str(demo_workspace), "修复登录 bug")
        assert result["recommended_profile"] == ""
        assert result["learning_state"] == "withheld_all_rolled_back"

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_profile_cli(self):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_profile_http(self):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


# ═════════════════════════════════════════════════════════════════════════════
# G-02: Verification Loop Strengthening
# ═════════════════════════════════════════════════════════════════════════════

class TestG02VerificationLoop:
    def test_verification_loop_class(self):
        from memory_center.core.verification.loop import VerificationLoop
        assert VerificationLoop is not None

    def test_verification_loop_start_and_status(self, demo_workspace: Path):
        from memory_center.core.verification.loop import VerificationLoop
        vl = VerificationLoop(str(demo_workspace))
        loop = vl.start("task-1", "Test task")
        assert loop["status"] == "started"
        assert loop["task_id"] == "task-1"
        status = vl.get_status("task-1")
        assert status["task_id"] == "task-1"

    def test_verification_loop_checklist(self, demo_workspace: Path):
        from memory_center.core.verification.loop import VerificationLoop
        vl = VerificationLoop(str(demo_workspace))
        items = vl.get_checklist("code_change")
        assert len(items) > 0
        assert isinstance(items[0], str)

    def test_verification_loop_generate_checklist(self, demo_workspace: Path):
        from memory_center.core.verification.loop import VerificationLoop
        vl = VerificationLoop(str(demo_workspace))
        result = vl.generate_checklist({"task_type": "bugfix"})
        assert "task_type" in result
        assert "items" in result

    def test_verification_loop_complete_phase(self, demo_workspace: Path):
        from memory_center.core.verification.loop import VerificationLoop
        vl = VerificationLoop(str(demo_workspace))
        vl.start("task-2", "Phase test")
        entry = vl.complete_phase("task-2", "analyze", {"findings": ["ok"]})
        assert entry["status"] == "completed"

    def test_verification_loop_verify_phase_records_feedback(self, demo_workspace: Path):
        from memory_center.core.verification.heuristics import HeuristicsRegister
        from memory_center.core.verification.loop import VerificationLoop

        vl = VerificationLoop(str(demo_workspace))
        started = vl.start("task-verify-feedback", "Phase verify feedback")
        entry = vl.complete_phase(
            started["loop_id"],
            "verify",
            {
                "candidate_type": "impact_analysis",
                "target": "ArticleFeignClient",
                "outcome": "confirmed",
                "evidence": [{"type": "test", "id": "ev-1"}],
            },
        )
        assert entry["feedback"]["recorded"] is True

        hr = HeuristicsRegister(str(demo_workspace))
        rows = hr.query(category="candidate-path")
        assert any(item.get("target") == "ArticleFeignClient" for item in rows)

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_verification_loop_cli(self, demo_workspace: Path):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


# ═════════════════════════════════════════════════════════════════════════════
# G-03: Pattern Promotion & Learned Heuristics
# ═════════════════════════════════════════════════════════════════════════════

class TestG03PatternPromotion:
    def test_pattern_promotion_class(self):
        from memory_center.core.verification.pattern_promotion import PatternPromotion
        assert PatternPromotion is not None

    def test_pattern_propose_and_list(self, demo_workspace: Path):
        from memory_center.core.verification.pattern_promotion import PatternPromotion
        pp = PatternPromotion(str(demo_workspace))
        proposal = pp.propose("case", "case-1", "test_pattern", "A test pattern", [{"e": 1}])
        assert proposal["status"] == "proposed"
        proposals = pp.list_proposals()
        assert isinstance(proposals, list)

    def test_pattern_promote(self, demo_workspace: Path):
        from memory_center.core.verification.pattern_promotion import PatternPromotion
        pp = PatternPromotion(str(demo_workspace))
        proposal = pp.propose("rule", "rule-1", "promote_test", "Should be promoted", [])
        result = pp.promote(proposal["promotion_id"])
        assert result["action"] == "promoted"

    def test_heuristics_register_class(self):
        from memory_center.core.verification.heuristics import HeuristicsRegister
        assert HeuristicsRegister is not None

    def test_heuristics_record_and_query(self, demo_workspace: Path):
        from memory_center.core.verification.heuristics import HeuristicsRegister
        hr = HeuristicsRegister(str(demo_workspace))
        entry = hr.record("test", "pattern_x", "trigger_y", "good", 0.8)
        assert "heuristic_id" in entry
        results = hr.query("test")
        assert isinstance(results, list)

    def test_heuristics_record_accepts_dict_payload(self, demo_workspace: Path):
        from memory_center.core.verification.heuristics import HeuristicsRegister
        hr = HeuristicsRegister(str(demo_workspace))
        entry = hr.record(
            {
                "category": "candidate-path",
                "candidate_type": "lookup_path",
                "target": "ArticleFeignClient",
                "outcome": "confirmed",
                "evidence": [{"type": "unit", "id": "ev-1"}],
                "weight_before": 0.55,
                "source": "test",
            }
        )
        assert entry["event_type"] == "candidate_feedback"
        results = hr.query("candidate-path")
        assert results[0]["target"] == "ArticleFeignClient"

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_pattern_promotion_cli(self, demo_workspace: Path):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_heuristics_cli(self, demo_workspace: Path):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_heuristics_explain_cli(self, demo_workspace: Path):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_heuristics_explain_http(self, demo_workspace: Path):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


# ═════════════════════════════════════════════════════════════════════════════
# G-04: Agent Runtime Audit
# ═════════════════════════════════════════════════════════════════════════════

class TestG04AgentRuntimeAudit:
    def test_audit_agent_runtime_function(self):
        from memory_center.core.audit.runtime import audit_agent_runtime
        assert callable(audit_agent_runtime)

    def test_audit_on_demo(self, demo_workspace: Path):
        from memory_center.core.audit.runtime import audit_agent_runtime
        result = audit_agent_runtime(str(demo_workspace))
        assert isinstance(result, dict)
        assert "score" in result
        assert "findings" in result

    def test_audit_findings_structure(self, demo_workspace: Path):
        from memory_center.core.audit.runtime import audit_agent_runtime
        result = audit_agent_runtime(str(demo_workspace))
        for finding in result["findings"]:
            assert "category" in finding
            assert "severity" in finding
            assert "message" in finding

    def test_audit_reports_missing_agent_mcp_bindings(self, demo_workspace: Path):
        from memory_center.core.audit.runtime import audit_agent_runtime
        result = audit_agent_runtime(str(demo_workspace))
        assert result["mcp_bindings"]["ok"] is False
        assert any(item["code"] == "mcp_binding_missing_or_stale" for item in result["findings"])

    def test_audit_fix_writes_agent_mcp_bindings(self, demo_workspace: Path):
        from memory_center.core.audit.runtime import audit_agent_runtime
        result = audit_agent_runtime(str(demo_workspace), fix=True)
        assert result["auto_fixed"] is True
        assert result["mcp_bindings"]["ok"] is True
        service_config = demo_workspace.parent.parent / "task-service" / ".codex" / "mcp.json"
        data = json.loads(service_config.read_text(encoding="utf-8"))
        # 5.0 起宿主绑定是 Streamable HTTP（直连常驻服务）；4.x 的 stdio
        # `memory-center-mcp --workspace <file>` 已退役，因此不再写 args。
        entry = data["mcpServers"]["memory-center"]
        assert entry["type"] == "http"
        assert entry["url"].endswith("/mcp")

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_runtime_audit_cli_fix_writes_bindings(self, demo_workspace: Path):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_setup_agent_cli_writes_bindings_and_next_steps(self, demo_workspace: Path):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    def test_runtime_audit_mcp_admin_force_writes_bindings(self, demo_workspace: Path):
        from memory_center.application.admin import build_admin_registry

        registry = build_admin_registry(workspace_file=str(demo_workspace), action="runtime_audit", force=True)
        result = registry.dispatch("runtime_audit")
        assert result["auto_fixed"] is True
        assert result["mcp_bindings"]["ok"] is True


# ═════════════════════════════════════════════════════════════════════════════
# G-05: Agent Usage Bundle Export
# ═════════════════════════════════════════════════════════════════════════════

class TestG05BundleExport:
    def test_generate_agent_bundle_codex(self, demo_workspace: Path):
        from memory_center.core.verification.bundle_export import generate_agent_bundle
        bundle = generate_agent_bundle(str(demo_workspace), agent="codex")
        assert bundle["agent"] == "codex"
        assert "contents" in bundle
        assert "agent_specific" in bundle

    def test_generate_agent_bundle_claude(self, demo_workspace: Path):
        from memory_center.core.verification.bundle_export import generate_agent_bundle
        bundle = generate_agent_bundle(str(demo_workspace), agent="claude")
        assert bundle["agent"] == "claude"

    def test_generate_agent_bundle_cursor(self, demo_workspace: Path):
        from memory_center.core.verification.bundle_export import generate_agent_bundle
        bundle = generate_agent_bundle(str(demo_workspace), agent="cursor")
        assert bundle["agent"] == "cursor"

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_bundle_export_cli(self, demo_workspace: Path):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    def test_bundle_no_private_paths(self, demo_workspace: Path):
        from memory_center.core.verification.bundle_export import generate_agent_bundle
        bundle = generate_agent_bundle(str(demo_workspace), agent="codex")
        import json
        content = json.dumps(bundle)
        # Should not contain real private paths
        assert "/Users/" not in content or "example" in content.lower()


# ═════════════════════════════════════════════════════════════════════════════
# G-06: HTTP Workbench Alignment
# ═════════════════════════════════════════════════════════════════════════════

class TestG06HTTPWorkbench:
    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_health_route(self):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_work_health_route(self, demo_workspace: Path):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_workflow_profile_route(self):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_verification_loop_route(self, demo_workspace: Path):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_runtime_audit_route(self, demo_workspace: Path):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_regression_alerts_route(self, demo_workspace: Path):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


# ═════════════════════════════════════════════════════════════════════════════
# G-07: Install & Build Flow
# ═════════════════════════════════════════════════════════════════════════════

class TestG07InstallBuild:
    def test_version_accessible(self):
        from memory_center import __version__
        assert isinstance(__version__, str)
        assert len(__version__) > 0

    def test_pyproject_has_entry_points(self):
        pyproject = Path("pyproject.toml")
        content = pyproject.read_text()
        assert "memory-center" in content
        assert "memory-center-mcp" in content

    def test_pyproject_installs_mcp_runtime_by_default(self):
        pyproject = Path("pyproject.toml")
        content = pyproject.read_text()
        import tomllib
        from packaging.requirements import Requirement

        dependencies = tomllib.loads(content)['project']['dependencies']
        assert any(Requirement(value).name == 'mcp' for value in dependencies)

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_three_entry_points_exist(self):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")
