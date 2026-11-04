"""B-01: Three-entry-point real behavior matrix tests.

Supplements test_capability_matrix.py (which verifies entry-point *existence*)
by actually *invoking* each entry point and verifying:
  1. Execution succeeds and returns a dict.
  2. All entry points for the same capability return the same key set.
  3. Declared core_fields match actual return structure (where applicable).
  4. Error semantics are consistent across CLI / HTTP / MCP.
  5. All entry points delegate to the same core backend function.
"""
from __future__ import annotations

import dataclasses
import inspect
import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from memory_center.core.foundation.capabilities import CAPABILITY_MAP

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_RUNNER = CliRunner()


def _to_dict(obj: Any) -> dict[str, Any]:
    """Convert dataclass or dict to a plain dict."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if isinstance(obj, dict):
        return obj
    raise TypeError(f"Expected dict or dataclass, got {type(obj)}")


def _cli_json(cmd_args: list[str]) -> dict[str, Any]:
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


def _http(route: str, params: dict | None = None, ws: str | None = None) -> Any:
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


def _assert_no_database_error(result: Any) -> None:
    """Ensure result is not a SQLite 'file is not a database' error."""
    text = json.dumps(result, default=str)
    assert "file is not a database" not in text


# ---------------------------------------------------------------------------
# Core-function return-key fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def _workflow_profile_keys() -> set:
    from memory_center.core.verification.workflow_profiles import get_workflow_profile
    return set(_to_dict(get_workflow_profile("quick-fix")).keys())


@pytest.fixture()
def _runtime_audit_keys(demo_workspace: Path) -> set:
    from memory_center.core.audit.runtime import audit_agent_runtime
    return set(audit_agent_runtime(str(demo_workspace)).keys())


@pytest.fixture()
def _regression_alerts_keys(demo_workspace: Path) -> set:
    from memory_center.core.benchmark.trending import check_regression_alerts
    return set(check_regression_alerts(str(demo_workspace)).keys())


@pytest.fixture()
def _parser_benchmark_keys(demo_workspace: Path) -> set:
    from memory_center.core.orchestrator import memory_eval_parser_benchmark

    return set(memory_eval_parser_benchmark(str(demo_workspace)).keys())


@pytest.fixture()
def _backend_consistency_keys(demo_workspace: Path) -> set:
    """纯 backend 结果 keys（MCP 测试直连 backend）。"""
    from memory_center.core.backend.query import UnifiedBackendQuery
    from memory_center.core.storage.workspace import WorkspaceStore

    store = WorkspaceStore(str(demo_workspace))
    with UnifiedBackendQuery(store.runtime_db_path) as backend:
        return set(backend.check_consistency(store.base_dir).keys())


@pytest.fixture()
def _backend_consistency_facade_keys(_backend_consistency_keys: set) -> set:
    """CLI/HTTP facade keys：backend 结果之上追加 jsonl_projection。

    application.admin.backend_consistency 会附加 JSONL 导出投影健康度
    （``jsonl_projection``），这是 facade 与 backend 唯一的有意差异。
    """
    return _backend_consistency_keys | {"jsonl_projection"}


@pytest.fixture()
def _graph_seed(demo_workspace_indexed: Path) -> str:
    """Return a node_id from the indexed graph for business-flow tests."""
    from memory_center.core.storage.runtime import RuntimeStore
    from memory_center.core.storage.workspace import WorkspaceStore

    store = WorkspaceStore(str(demo_workspace_indexed))
    unified = RuntimeStore(store.graph_db_path)
    try:
        rows = unified.query("MATCH (n) RETURN n.node_id LIMIT 1")
        if rows:
            row = rows[0]
            return row[0] if isinstance(row, (list, tuple)) else str(row)
    except Exception:
        pass
    finally:
        unified.close()
    pytest.skip("No graph nodes available in demo workspace")


# ---------------------------------------------------------------------------
# 1. Three-entry-point execution — real invocation + key-set consistency
# ---------------------------------------------------------------------------


class TestThreeEntryPointExecution:
    """Invoke each three-entry-point capability through all three channels,
    verify it returns a dict, and verify key sets are consistent."""

    # ---- workflow-profile (no workspace, pure data) ----

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_workflow_profile_cli(self, _workflow_profile_keys):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_workflow_profile_http(self, _workflow_profile_keys):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    def test_workflow_profile_mcp(self, _workflow_profile_keys):
        from memory_center.core.verification.workflow_profiles import get_workflow_profile

        result = _to_dict(get_workflow_profile("quick-fix"))
        assert set(result.keys()) == _workflow_profile_keys

    # ---- runtime-audit (needs workspace) ----

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_runtime_audit_cli(self, demo_workspace: Path, _runtime_audit_keys):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_runtime_audit_http(self, demo_workspace: Path, _runtime_audit_keys):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    def test_runtime_audit_mcp(self, demo_workspace: Path, _runtime_audit_keys):
        from memory_center.core.audit.runtime import audit_agent_runtime

        result = audit_agent_runtime(str(demo_workspace))
        assert isinstance(result, dict)
        _assert_no_database_error(result)
        assert set(result.keys()) == _runtime_audit_keys

    # ---- regression-alerts (needs workspace) ----

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_regression_alerts_cli(self, demo_workspace: Path, _regression_alerts_keys):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_regression_alerts_http(self, demo_workspace: Path, _regression_alerts_keys):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    def test_regression_alerts_mcp(self, demo_workspace: Path, _regression_alerts_keys):
        from memory_center.core.benchmark.trending import check_regression_alerts

        result = check_regression_alerts(str(demo_workspace))
        assert isinstance(result, dict)
        _assert_no_database_error(result)
        assert set(result.keys()) == _regression_alerts_keys

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_parser_benchmark_cli(self, demo_workspace: Path, _parser_benchmark_keys):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_parser_benchmark_http(self, demo_workspace: Path, _parser_benchmark_keys):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    def test_parser_benchmark_mcp(self, demo_workspace: Path, _parser_benchmark_keys):
        from memory_center.core.orchestrator import memory_eval_parser_benchmark

        result = memory_eval_parser_benchmark(str(demo_workspace))
        assert isinstance(result, dict)
        _assert_no_database_error(result)
        assert set(result.keys()) == _parser_benchmark_keys

    # ---- backend-consistency (needs workspace with db) ----

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_backend_consistency_cli(
        self, demo_workspace: Path, _backend_consistency_facade_keys
    ):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_backend_consistency_http(
        self, demo_workspace: Path, _backend_consistency_facade_keys
    ):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    def test_backend_consistency_mcp(
        self, demo_workspace: Path, _backend_consistency_keys
    ):
        from memory_center.core.backend.query import UnifiedBackendQuery
        from memory_center.core.storage.workspace import WorkspaceStore

        ws = str(demo_workspace)
        store = WorkspaceStore(ws)
        with UnifiedBackendQuery(store.runtime_db_path) as backend:
            result = backend.check_consistency(store.base_dir)
        assert isinstance(result, dict)
        _assert_no_database_error(result)
        assert set(result.keys()) == _backend_consistency_keys

    # ---- verification-loop (needs workspace) ----

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_verification_loop_cli(self, demo_workspace: Path):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_verification_loop_http(self, demo_workspace: Path):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    def test_verification_loop_mcp(self, demo_workspace: Path):
        from memory_center.core.verification.loop import VerificationLoop

        ws = str(demo_workspace)
        vl = VerificationLoop(ws)
        checklist = vl.generate_checklist({"task_type": "general", "workspace": ws})
        status = vl.get_status("default")
        assert isinstance(checklist, dict)
        assert isinstance(status, dict)
        assert "task_type" in checklist
        assert "items" in checklist
        assert "task_id" in status
        assert "status" in status

    # ---- business-flow (needs indexed workspace + seed) ----

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_business_flow_cli(
        self, demo_workspace_indexed: Path, _graph_seed: str
    ):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_business_flow_http(
        self, demo_workspace_indexed: Path, _graph_seed: str
    ):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_business_flow_mcp(
        self, demo_workspace_indexed: Path, _graph_seed: str
    ):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    # ---- business-flow-impact (needs indexed workspace + node_id) ----

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_business_flow_impact_cli(
        self, demo_workspace_indexed: Path, _graph_seed: str
    ):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_business_flow_impact_http(
        self, demo_workspace_indexed: Path, _graph_seed: str
    ):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_business_flow_impact_mcp(
        self, demo_workspace_indexed: Path, _graph_seed: str
    ):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


# ---------------------------------------------------------------------------
# 2. Single / dual entry-point capabilities
# ---------------------------------------------------------------------------


class TestSingleEntryPointBehavior:
    """Capabilities with only HTTP + MCP (or MCP-only) entry points."""

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_context_pack_http(self, demo_workspace: Path):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    def test_context_pack_mcp(self, demo_workspace: Path):
        cap = CAPABILITY_MAP["context-pack"]
        from memory_center.core.context.pack import ContextPackBuilder

        builder = ContextPackBuilder(str(demo_workspace))
        pack = builder.build(query="Spring Cloud Gateway routing", intent="auto")
        result = {
            "workflow": "mc-context-pack",
            "query": pack.query,
            "intent": pack.intent,
            "entrypoints": pack.entrypoints,
            "relationships": pack.relationships,
            "snippets": pack.snippets,
            "risks": pack.risks,
            "checklist": pack.checklist,
            "freshness": pack.freshness,
            "token_estimate": pack.token_estimate,
        }
        for field in cap.core_fields:
            assert field in result, (
                f"Missing core_field '{field}' in MCP context-pack"
            )

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_freshness_http(self, demo_workspace: Path):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    def test_freshness_mcp(self, demo_workspace: Path):
        from memory_center.core.freshness.status import IndexFreshnessService

        svc = IndexFreshnessService(str(demo_workspace))
        banner = svc.banner()
        result = {"workflow": "mc-freshness", **banner}
        assert "banner" in result or "freshness" in result

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_onboard_http(self, demo_workspace: Path):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    def test_onboard_mcp(self, demo_workspace: Path):
        cap = CAPABILITY_MAP["onboard"]
        from memory_center.core.onboarding.tour import ArchitectureTourGenerator
        from memory_center.core.storage.runtime import RuntimeStore
        from memory_center.core.storage.workspace import WorkspaceStore

        ws = str(demo_workspace)
        store = WorkspaceStore(ws)
        unified = RuntimeStore(store.graph_db_path)
        try:
            gen = ArchitectureTourGenerator(unified)
            tour = gen.generate_tour(persona="developer")
            result = {"workflow": "mc-onboard", "tour": tour.to_dict()}
        finally:
            unified.close()
        for field in cap.core_fields:
            assert field in result, (
                f"Missing core_field '{field}' in MCP onboard"
            )

    def test_domain_mcp(self, demo_workspace: Path):
        cap = CAPABILITY_MAP["domain"]
        from memory_center.core.domain.extractor import BusinessDomainExtractor
        from memory_center.core.storage.runtime import RuntimeStore
        from memory_center.core.storage.workspace import WorkspaceStore

        ws = str(demo_workspace)
        store = WorkspaceStore(ws)
        unified = RuntimeStore(store.graph_db_path)
        try:
            extractor = BusinessDomainExtractor(unified)
            domains = extractor.extract_domains()
            result = {
                "workflow": "mc-domain",
                "domains": [d.to_dict() for d in domains],
                "domain_count": len(domains),
            }
        finally:
            unified.close()
        for field in cap.core_fields:
            assert field in result, (
                f"Missing core_field '{field}' in MCP domain"
            )


# ---------------------------------------------------------------------------
# 3. Cross-entry-point field consistency
# ---------------------------------------------------------------------------


class TestEntryPointFieldConsistency:
    """Verify that CLI and HTTP return dicts share the same key set
    for the same capability, matching the core function's actual output."""

    @pytest.mark.parametrize(
        "cap_name,cli_args,http_route,http_params",
        [
            (
                "regression-alerts",
                None,  # filled with --workspace from fixture
                "/workspace/regression-alerts",
                {},
            ),
            (
                "backend-consistency",
                None,
                "/workspace/backend-consistency",
                {},
            ),
        ],
    )
    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_cli_and_http_return_same_keys(
        self, cap_name, cli_args, http_route, http_params, demo_workspace: Path
    ):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


# ---------------------------------------------------------------------------
# 4. Declared core_fields vs actual return structure
# ---------------------------------------------------------------------------


class TestCoreFieldAlignment:
    """Check whether declared core_fields in the capability matrix match
    the actual return structure from the backend function.

    Mismatches indicate the matrix declaration needs updating.
    """

    def test_runtime_audit_core_fields(self, demo_workspace: Path):
        from memory_center.core.audit.runtime import audit_agent_runtime

        cap = CAPABILITY_MAP["runtime-audit"]
        actual_keys = set(audit_agent_runtime(str(demo_workspace)).keys())
        for field in cap.core_fields:
            assert field in actual_keys, (
                f"core_field '{field}' not in actual keys: {sorted(actual_keys)}"
            )

    def test_regression_alerts_core_fields(self, demo_workspace: Path):
        from memory_center.core.benchmark.trending import check_regression_alerts

        cap = CAPABILITY_MAP["regression-alerts"]
        actual_keys = set(check_regression_alerts(str(demo_workspace)).keys())
        for field in cap.core_fields:
            assert field in actual_keys, (
                f"core_field '{field}' not in actual keys: {sorted(actual_keys)}"
            )

    def test_parser_benchmark_core_fields(self, demo_workspace: Path):
        from memory_center.core.orchestrator import memory_eval_parser_benchmark

        cap = CAPABILITY_MAP["parser-benchmark"]
        actual_keys = set(memory_eval_parser_benchmark(str(demo_workspace)).keys())
        for field in cap.core_fields:
            assert field in actual_keys, (
                f"core_field '{field}' not in actual keys: {sorted(actual_keys)}"
            )

    def test_backend_consistency_core_fields(self, demo_workspace: Path):
        from memory_center.core.backend.query import UnifiedBackendQuery
        from memory_center.core.storage.workspace import WorkspaceStore

        cap = CAPABILITY_MAP["backend-consistency"]
        store = WorkspaceStore(str(demo_workspace))
        with UnifiedBackendQuery(store.runtime_db_path) as backend:
            actual_keys = set(backend.check_consistency(store.base_dir).keys())
        for field in cap.core_fields:
            assert field in actual_keys, (
                f"core_field '{field}' not in actual keys: {sorted(actual_keys)}"
            )

    def test_freshness_core_fields(self, demo_workspace: Path):
        from memory_center.core.freshness.status import IndexFreshnessService

        cap = CAPABILITY_MAP["freshness"]
        svc = IndexFreshnessService(str(demo_workspace))
        banner = svc.banner()
        result = {"workflow": "mc-freshness", **banner}
        for field in cap.core_fields:
            assert field in result, (
                f"core_field '{field}' not in actual keys: {sorted(result.keys())}"
            )

    def test_workflow_profile_core_fields(self):
        from memory_center.core.verification.workflow_profiles import (
            get_workflow_profile,
        )

        cap = CAPABILITY_MAP["workflow-profile"]
        actual_keys = set(_to_dict(get_workflow_profile("quick-fix")).keys())
        for field in cap.core_fields:
            assert field in actual_keys, (
                f"core_field '{field}' not in actual keys: {sorted(actual_keys)}"
            )

    def test_verification_loop_core_fields(self, demo_workspace: Path):
        from memory_center.core.verification.loop import VerificationLoop

        cap = CAPABILITY_MAP["verification-loop"]
        ws = str(demo_workspace)
        vl = VerificationLoop(ws)
        checklist = vl.generate_checklist({"task_type": "general", "workspace": ws})
        status = vl.get_status("default")
        actual_keys = set({"checklist": checklist, "status": status}.keys())
        for field in cap.core_fields:
            assert field in actual_keys, (
                f"core_field '{field}' not in actual keys: {sorted(actual_keys)}"
            )


# ---------------------------------------------------------------------------
# 5. Error semantic consistency
# ---------------------------------------------------------------------------


class TestErrorSemanticConsistency:
    """Verify that error conditions produce consistent behavior across
    entry points — no 'file is not a database' leaks."""

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_cli_invalid_workspace_exits_nonzero(self):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_http_invalid_workspace_raises_file_not_found(self):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_http_missing_workspace_raises_value_error(self):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    def test_mcp_invalid_workspace_raises(self):
        from memory_center.core.audit.runtime import audit_agent_runtime

        with pytest.raises((FileNotFoundError, OSError)):
            audit_agent_runtime("/nonexistent/workspace.yaml")
        try:
            audit_agent_runtime("/nonexistent/workspace.yaml")
        except Exception as exc:
            assert "file is not a database" not in str(exc)

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_cli_regression_alerts_invalid_workspace(self):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    def test_mcp_regression_alerts_invalid_workspace(self):
        from memory_center.core.benchmark.trending import check_regression_alerts

        with pytest.raises((FileNotFoundError, OSError)):
            check_regression_alerts("/nonexistent/path/workspace.yaml")
        try:
            check_regression_alerts("/nonexistent/path/workspace.yaml")
        except Exception as exc:
            assert "file is not a database" not in str(exc)

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_cli_parser_benchmark_invalid_workspace(self):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    def test_mcp_parser_benchmark_invalid_workspace(self):
        from memory_center.core.orchestrator import memory_eval_parser_benchmark

        with pytest.raises((FileNotFoundError, OSError)):
            memory_eval_parser_benchmark("/nonexistent/path/workspace.yaml")
        try:
            memory_eval_parser_benchmark("/nonexistent/path/workspace.yaml")
        except Exception as exc:
            assert "file is not a database" not in str(exc)


# ---------------------------------------------------------------------------
# 6. Backend function sharing — same core function across entry points
# ---------------------------------------------------------------------------


class TestBackendFunctionSharing:
    """Verify that CLI, HTTP, and MCP entry points for the same capability
    all delegate to the same core backend function."""

    BACKEND_FUNCTIONS = {
        "workflow-profile": "get_workflow_profile",
        "runtime-audit": "audit_agent_runtime",
        "regression-alerts": "check_regression_alerts",
        "parser-benchmark": "memory_eval_parser_benchmark",
        "verification-loop": "VerificationLoop",
        "business-flow": "extract_business_flows_for_workspace",
        "business-flow-impact": "business_flow_impact_for_workspace",
    }

    def test_cli_uses_shared_backend(self):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    def test_http_uses_shared_backend(self):
        from memory_center.application import admin, analysis, quality_gates

        http_src = "\n".join(inspect.getsource(module) for module in (admin, analysis, quality_gates))
        for cap_name, func_name in self.BACKEND_FUNCTIONS.items():
            assert func_name in http_src, (
                f"HTTP route registry does not reference backend function "
                f"'{func_name}' for capability '{cap_name}'"
            )

    def test_mcp_uses_shared_backend(self):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")
