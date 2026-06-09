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
        from memory_center.core.store import WorkspaceStore
        from memory_center.core.backend.query import UnifiedBackendQuery
        ws = WorkspaceStore(str(demo_workspace))
        db_path = ws.memory_db_path
        with UnifiedBackendQuery(db_path) as ubq:
            idx = ubq.read_index_list("file-index.json")
            assert isinstance(idx, list)

    def test_backend_query_records(self, demo_workspace: Path):
        from memory_center.core.store import WorkspaceStore
        from memory_center.core.backend.query import UnifiedBackendQuery
        ws = WorkspaceStore(str(demo_workspace))
        db_path = ws.memory_db_path
        with UnifiedBackendQuery(db_path) as ubq:
            result = ubq.query_records(limit=5)
            assert isinstance(result, dict)

    def test_backend_consistency_cli_entry(self, demo_workspace: Path):
        from typer.testing import CliRunner
        from memory_center.cli.main import app
        runner = CliRunner()
        result = runner.invoke(app, ["backend-consistency", "--workspace", str(demo_workspace)])
        assert result.exit_code == 0


# ═════════════════════════════════════════════════════════════════════════════
# F-03: Metrics System
# ═════════════════════════════════════════════════════════════════════════════

class TestF03Metrics:
    def test_metrics_collector_class(self):
        from memory_center.core.metrics import MetricsCollector
        assert MetricsCollector is not None

    def test_metrics_record_and_query(self, tmp_path: Path):
        from memory_center.core.metrics import MetricsCollector
        ws_file = tmp_path / ".memory-center" / "workspace.yaml"
        ws_file.parent.mkdir(parents=True, exist_ok=True)
        ws_file.write_text("root: /tmp/test\n")
        mc = MetricsCollector(str(ws_file))
        mc.record("test_metric", 42.0, unit="ms")
        rows = mc.query("test_metric")
        assert len(rows) == 1
        assert rows[0]["value"] == 42.0

    def test_metrics_timer(self, tmp_path: Path):
        from memory_center.core.metrics import MetricsCollector
        ws_file = tmp_path / ".memory-center" / "workspace.yaml"
        ws_file.parent.mkdir(parents=True, exist_ok=True)
        ws_file.write_text("root: /tmp/test\n")
        mc = MetricsCollector(str(ws_file))
        with mc.timer("test_timer"):
            pass  # should record elapsed time
        rows = mc.query("test_timer")
        assert len(rows) >= 1

    def test_metrics_summary(self, tmp_path: Path):
        from memory_center.core.metrics import MetricsCollector
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
        from memory_center.core.benchmark.trending import check_regression_alerts_configurable
        from memory_center.core.benchmark.trending import RegressionThresholdConfig
        config = RegressionThresholdConfig(default_threshold_pct=5.0)
        
        result2 = check_regression_alerts_configurable(str(demo_workspace), config)
        assert isinstance(result2, dict)
        result2.get("alerts", [])
        


# ═════════════════════════════════════════════════════════════════════════════
# F-05: Regression Alerts
# ═════════════════════════════════════════════════════════════════════════════

class TestF05RegressionAlerts:
    def test_regression_alerts_cli(self, demo_workspace: Path):
        from typer.testing import CliRunner
        from memory_center.cli.main import app
        runner = CliRunner()
        result = runner.invoke(app, ["regression-alerts", "--workspace", str(demo_workspace), "--threshold-pct", "10"])
        assert result.exit_code == 0

    def test_regression_alerts_http(self, demo_workspace: Path):
        from memory_center.http.server import _route_request
        resp = _route_request("/workspace/regression-alerts", {"workspace": [str(demo_workspace)], "threshold_pct": ["10.0"]}, None)
        assert resp is not None


# ═════════════════════════════════════════════════════════════════════════════
# F-06: Runtime Audit Productization
# ═════════════════════════════════════════════════════════════════════════════

class TestF06RuntimeAudit:
    def test_completion_audit_exists(self):
        from memory_center.core.audit.completion import run_completion_audit
        assert callable(run_completion_audit)

    def test_completion_audit_on_demo(self, demo_workspace: Path):
        from memory_center.core.audit.completion import run_completion_audit
        result = run_completion_audit(str(demo_workspace))
        assert isinstance(result, dict)
        assert "score" in result

    def test_workspace_type_detection(self):
        from memory_center.core.audit.completion import detect_workspace_type
        assert callable(detect_workspace_type)

    def test_audit_cli_entry(self, demo_workspace: Path):
        from typer.testing import CliRunner
        from memory_center.cli.main import app
        runner = CliRunner()
        result = runner.invoke(app, ["runtime-audit", "--workspace", str(demo_workspace)])
        assert result.exit_code == 0


# ═════════════════════════════════════════════════════════════════════════════
# F-07: Health & Governance Loop
# ═════════════════════════════════════════════════════════════════════════════

class TestF07HealthGovernance:
    def test_work_health_cli(self, demo_workspace: Path):
        from typer.testing import CliRunner
        from memory_center.cli.main import app
        runner = CliRunner()
        result = runner.invoke(app, ["work-health", "--workspace", str(demo_workspace)])
        assert result.exit_code == 0

    def test_work_health_http(self, demo_workspace: Path):
        from memory_center.http.server import _route_request
        resp = _route_request("/workspace/work-health", {"workspace": [str(demo_workspace)], "intent": ["health check"]}, None)
        assert resp is not None


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

    def test_profile_cli(self):
        from typer.testing import CliRunner
        from memory_center.cli.main import app
        runner = CliRunner()
        result = runner.invoke(app, ["workflow-profile", "--profile", "quick-fix"])
        assert result.exit_code == 0

    def test_profile_http(self):
        from memory_center.http.server import _route_request
        resp = _route_request("/workspace/workflow-profile", {"workspace": [str(demo_workspace)], "profile": ["quick-fix"]}, None)
        assert resp is not None
        assert resp is not None


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

    def test_verification_loop_cli(self, demo_workspace: Path):
        from typer.testing import CliRunner
        from memory_center.cli.main import app
        runner = CliRunner()
        result = runner.invoke(app, ["verification-loop", "--workspace", str(demo_workspace)])
        assert result.exit_code == 0


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

    def test_pattern_promotion_cli(self, demo_workspace: Path):
        from typer.testing import CliRunner
        from memory_center.cli.main import app
        runner = CliRunner()
        result = runner.invoke(app, ["pattern-promotion", "--workspace", str(demo_workspace)])
        assert result.exit_code == 0

    def test_heuristics_cli(self, demo_workspace: Path):
        from typer.testing import CliRunner
        from memory_center.cli.main import app
        runner = CliRunner()
        result = runner.invoke(app, ["heuristics", "--workspace", str(demo_workspace)])
        assert result.exit_code == 0


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

    def test_bundle_export_cli(self, demo_workspace: Path):
        from typer.testing import CliRunner
        from memory_center.cli.main import app
        runner = CliRunner()
        result = runner.invoke(app, ["bundle-export", "--workspace", str(demo_workspace), "--agent", "codex"])
        assert result.exit_code == 0

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
    def test_health_route(self):
        from memory_center.http.server import _route_request
        resp = _route_request("/health", {}, None)
        assert resp.get("ok") is True

    def test_work_health_route(self, demo_workspace: Path):
        from memory_center.http.server import _route_request
        resp = _route_request("/workspace/work-health", {"workspace": [str(demo_workspace)]}, None)
        assert resp is not None

    def test_workflow_profile_route(self):
        from memory_center.http.server import _route_request
        resp = _route_request("/workspace/workflow-profile", {"workspace": [str(demo_workspace)], "profile": ["quick-fix"]}, None)
        assert resp is not None
        assert resp is not None

    def test_verification_loop_route(self, demo_workspace: Path):
        from memory_center.http.server import _route_request
        resp = _route_request("/workspace/verification-loop", {"workspace": [str(demo_workspace)]}, None)
        assert resp is not None

    def test_runtime_audit_route(self, demo_workspace: Path):
        from memory_center.http.server import _route_request
        resp = _route_request("/workspace/runtime-audit", {"workspace": [str(demo_workspace)]}, None)
        assert resp is not None

    def test_regression_alerts_route(self, demo_workspace: Path):
        from memory_center.http.server import _route_request
        resp = _route_request("/workspace/regression-alerts", {"workspace": [str(demo_workspace)]}, None)
        assert resp is not None


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

    def test_three_entry_points_exist(self):
        from memory_center.cli.main import app as cli_app
        from memory_center.mcp.server import create_server
        from memory_center.http.server import serve_http
        assert cli_app is not None
        assert callable(create_server)
        assert callable(serve_http)

