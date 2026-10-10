"""B-01: CLI / MCP / HTTP capability matrix tests.

Verifies that all 14 required capabilities have the expected entry-point
coverage and that entry points behave correctly with valid/invalid/empty
workspaces.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from memory_center.core.foundation.capabilities import (
    CAPABILITIES,
    CAPABILITY_MAP,
    all_cli_commands,
    all_http_routes,
    all_mcp_admin_actions,
    all_mcp_tools,
)

# ---------------------------------------------------------------------------
# 1. Matrix completeness: all 14 capabilities exist
# ---------------------------------------------------------------------------

REQUIRED_CAPABILITIES = [
    "context-pack",
    "freshness",
    "onboard",
    "domain",
    "business-flow",
    "business-flow-impact",
    "verification-loop",
    "workflow-profile",
    "runtime-audit",
    "regression-alerts",
    "backend-consistency",
    "drill-ref",
    "drill-timeline",
    "drill-task",
]


class TestMatrixCompleteness:
    """All 14 required capabilities must be present and have core fields."""

    def test_all_required_capabilities_present(self):
        for name in REQUIRED_CAPABILITIES:
            assert name in CAPABILITY_MAP, f"Missing capability: {name}"

    def test_each_capability_has_entries(self):
        for name in REQUIRED_CAPABILITIES:
            cap = CAPABILITY_MAP[name]
            assert len(cap.entries) > 0, f"{name} has no entry points"

    def test_each_capability_has_core_fields(self):
        for name in REQUIRED_CAPABILITIES:
            cap = CAPABILITY_MAP[name]
            assert len(cap.core_fields) > 0, f"{name} has no core_fields"

    def test_each_capability_has_error_semantics(self):
        for name in REQUIRED_CAPABILITIES:
            cap = CAPABILITY_MAP[name]
            assert cap.error_semantics, f"{name} has no error_semantics"


# ---------------------------------------------------------------------------
# 2. CLI coverage: commands exist in the real CLI app
# ---------------------------------------------------------------------------

class TestCLICoverage:
    """Verify every CLI entry in the matrix is a real Typer command."""

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_cli_commands_are_registered(self):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


# ---------------------------------------------------------------------------
# 3. HTTP coverage: routes exist in _route_request
# ---------------------------------------------------------------------------

class TestHTTPCoverage:
    """Verify every HTTP entry in the matrix is handled in _route_request."""

    @pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
    def test_http_routes_are_handled(self) -> None:
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


# ---------------------------------------------------------------------------
# 4. MCP coverage: tool names and mc_admin actions exist
# ---------------------------------------------------------------------------

class TestMCPCoverage:
    """Verify every MCP entry in the matrix is registered."""

    def test_mcp_tools_are_defined(self):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    def test_mcp_admin_actions_in_dispatch(self):
        """Check that mc_admin's action registry contains every action key."""
        # ``mc_admin`` now delegates to ``application.admin.build_admin_registry``,
        # so the action table lives there.  The MCP server still references the
        # registry indirectly, so we inspect the canonical source of truth.
        from memory_center.application import admin as admin_mod
        src = inspect.getsource(admin_mod)
        for cap in CAPABILITIES:
            for entry in cap.entries:
                if entry.kind == "mcp_admin_action":
                    # Actions are keys in the _DISPATCH dict
                    assert f'"{entry.identifier}"' in src, (
                        f"MCP admin action '{entry.identifier}' for capability "
                        f"'{cap.name}' not found in application admin registry"
                    )


# ---------------------------------------------------------------------------
# 5. Entry point helpers return correct data
# ---------------------------------------------------------------------------

class TestEntryPointHelpers:
    """Verify the helper functions return expected aggregated data."""

    def test_all_cli_commands_returns_non_empty(self):
        cmds = all_cli_commands()
        assert len(cmds) > 0

    def test_all_http_routes_returns_non_empty(self):
        routes = all_http_routes()
        assert len(routes) > 0

    def test_all_mcp_tools_returns_non_empty(self):
        tools = all_mcp_tools()
        assert len(tools) > 0

    def test_all_mcp_admin_actions_returns_non_empty(self):
        actions = all_mcp_admin_actions()
        assert len(actions) > 0

    def test_domain_only_has_mcp_tool(self):
        """domain capability should only have mc_domain, no CLI/HTTP."""
        entries = CAPABILITY_MAP["domain"].entries
        kinds = {e.kind for e in entries}
        assert "mcp_tool" in kinds
        assert "cli" not in kinds
        assert "http" not in kinds

    def test_context_pack_has_http_and_mcp_no_cli(self):
        entries = CAPABILITY_MAP["context-pack"].entries
        kinds = {e.kind for e in entries}
        assert "http" in kinds
        assert "mcp_tool" in kinds
        assert "cli" not in kinds


# ---------------------------------------------------------------------------
# 6. HTTP entry: invalid / empty / valid workspace
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
class TestHTTPWorkspaceParsing:
    """Test that _route_request handles invalid/empty/valid workspaces."""

    def _route(self, path: str, params: dict, ws: str | None = None):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    def test_health_returns_ok(self):
        result = self._route("/health", {})
        assert isinstance(result, dict)
        assert result.get("ok") is True

    def test_invalid_workspace_raises_not_database_error(self):
        """A non-existent workspace raises FileNotFoundError, not
        DatabaseError('file is not a database'). The HTTP handler layer
        wraps this, but _route_request itself propagates the error."""
        with pytest.raises(FileNotFoundError):
            self._route(
                "/workspace/status",
                {"workspace": ["/nonexistent/path/workspace.yaml"]},
            )

    def test_empty_workspace_no_crash(self):
        """Calling /health with empty workspace should still work."""
        result = self._route("/health", {})
        assert isinstance(result, dict)

    def test_valid_workspace_status(self, demo_workspace: Path):
        ws = str(demo_workspace)
        result = self._route(
            "/workspace/status",
            {"workspace": [ws]},
            ws,
        )
        assert isinstance(result, dict)
        assert "workspace" in result or "status" in result


# ---------------------------------------------------------------------------
# 7. CLI entry: invalid workspace smoke
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
class TestCLIWorkspaceParsing:
    """Test that CLI commands handle invalid workspace gracefully."""

    def _run(self, *args: str):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    def test_status_with_valid_workspace(self, demo_workspace: Path):
        ws = str(demo_workspace)
        result = self._run("status", "--workspace", ws)
        assert result.exit_code == 0
        assert isinstance(result.output, str)
        assert "file is not a database" not in result.output

    def test_backend_consistency_with_valid_workspace(self, demo_workspace: Path):
        ws = str(demo_workspace)
        result = self._run("backend-consistency", "--workspace", ws)
        assert result.exit_code == 0
        assert "file is not a database" not in result.output


# ---------------------------------------------------------------------------
# 8. Source-code level: workspace.yaml is never passed to RuntimeStore/RuntimeStore
# ---------------------------------------------------------------------------

class TestWorkspaceParsingContract:
    """Verify that entry points don't open workspace.yaml as a database."""

    def test_http_server_uses_workspace_store(self):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")

    def test_mcp_server_uses_workspace_store(self):
        pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")
