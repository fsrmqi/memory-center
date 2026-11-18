"""Truthfulness checks for the 5.0 entry-point registry.

Every identifier declared in ``core.foundation.entry_registry`` is verified
against the **running** service, not against source text:

* MCP tool names come from the real ``tools/list`` manager;
* HTTP ``(method, path)`` pairs come from the real FastAPI routers;
* console scripts are compared with ``pyproject.toml [project.scripts]``.

The retired 4.x identifiers are kept only as a denylist. These tests make sure
they neither reappear in the registry nor become reachable 5.0 surfaces, while
still resolving in the engine-side admin registry (an engine contract, not a
user entry point).
"""
from __future__ import annotations

try:
    import tomllib
except ImportError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib

from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from starlette.routing import Mount

from memory_center.core.foundation import entry_registry as reg

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def live_service():
    """Build the real app once; no lifespan / filesystem writes are needed."""
    from memory_center.service.app import create_service_app
    from memory_center.service.config import ServiceConfig
    from memory_center.service.governance_routes import governance_router
    from memory_center.service.platform_routes import platform_router
    from memory_center.service.workspace_routes import workspace_router

    # ServiceConfig only stores the path; create_service_app does not touch it
    # until lifespan runs, so no temporary directory is required here.
    app = create_service_app(ServiceConfig(ROOT / "__entry_registry_unused__"))

    boundary = next(
        mount.app for mount in app.routes
        if isinstance(mount, Mount) and type(mount.app).__name__ == "MCPBoundary"
    )
    # FastMCP's tool manager is the same source that serves tools/list. Using
    # the public list_tools() coroutine would need a request context, so read
    # the manager directly; a changed SDK API fails this test loudly.
    tool_names = frozenset(tool.name for tool in boundary.mcp._tool_manager.list_tools())

    http_routes = set()
    for route in app.routes:
        if isinstance(route, APIRoute):
            http_routes.update((method, route.path) for method in route.methods)
    for factory in (workspace_router, platform_router, governance_router):
        for route in factory().routes:
            http_routes.update((method, route.path) for method in route.methods)

    mounts = {(mount.path, type(mount.app).__name__)
              for mount in app.routes if isinstance(mount, Mount)}
    return {
        "tool_names": tool_names,
        "http_routes": http_routes,
        "mounts": mounts,
        "mcp_path": boundary.mcp.settings.streamable_http_path,
    }


class TestRegistryShape:
    def test_registry_is_non_empty_and_every_kind_is_live(self):
        assert reg.ENTRY_POINTS, "5.0 registry lost all entries"
        assert reg.LIVE_ENTRY_KINDS, "no kind is classified as a live 5.0 entry"
        kinds = {e.kind for e in reg.ENTRY_POINTS}
        assert kinds <= set(reg.LIVE_ENTRY_KINDS), (
            f"unclassified kinds: {sorted(kinds - set(reg.LIVE_ENTRY_KINDS))}"
        )
        assert not any(kind.startswith("legacy") for kind in kinds)

    def test_no_duplicate_identifiers_within_a_kind(self):
        seen = [(e.kind, e.identifier, e.method) for e in reg.ENTRY_POINTS]
        assert len(seen) == len(set(seen)), "duplicate entry declaration"

    def test_every_entry_has_an_authoritative_source(self):
        for e in reg.ENTRY_POINTS:
            assert e.identifier, "empty identifier"
            assert e.source, f"{e.kind}:{e.identifier} has no source"

    def test_helpers_agree_with_the_declared_data(self):
        assert reg.mcp_tool_names() == tuple(e.identifier for e in reg.MCP_TOOLS)
        assert reg.http_endpoints() == tuple((e.method, e.identifier) for e in reg.HTTP_ENDPOINTS)
        assert reg.cli_launcher_names() == tuple(e.identifier for e in reg.CLI_LAUNCHERS)
        assert reg.entry_points_by_kind(reg.KIND_MCP_TOOL) == reg.MCP_TOOLS
        assert reg.entry_points_by_kind("unknown-kind") == ()


class TestRegistryMatchesRunningService:
    def test_mcp_tools_match_live_tools_list(self, live_service):
        declared = set(reg.mcp_tool_names())
        live = set(live_service["tool_names"])
        assert declared == live, (
            f"registry-only: {sorted(declared - live)}; live-only: {sorted(live - declared)}.\n"
            "Step 1: update MCP_TOOLS to the real tools/list response.\n"
            "Step 2: update docs/MCP_GUIDE.md and docs/USER_GUIDE.md tool lists."
        )

    def test_http_endpoints_exist_in_real_routers(self, live_service):
        live = live_service["http_routes"]
        for method, path in reg.http_endpoints():
            assert (method, path) in live, (
                f"{method} {path} is declared but not registered by any 5.0 router.\n"
                "Step 1: check the router prefix in service/*_routes.py.\n"
                "Step 2: fix the declaration or remove the route from the registry."
            )

    def test_mcp_endpoint_and_admin_page_are_mounted(self, live_service):
        assert reg.MCP_ENDPOINTS[0].identifier == live_service["mcp_path"] == "/mcp"
        assert ("", "MCPBoundary") in live_service["mounts"]
        assert ("/admin", "StaticFiles") in live_service["mounts"]
        assert ("GET", "/") in live_service["http_routes"]

    def test_cli_launchers_match_pyproject_console_scripts(self):
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        scripts = set(data["project"]["scripts"])
        assert set(reg.cli_launcher_names()) == scripts, (
            "Step 1: compare CLI_LAUNCHERS with pyproject [project.scripts].\n"
            "Step 2: a new script is a launcher, never a memory-center subcommand."
        )


class TestRetiredFourXNamesStayRetired:
    """The 35 legacy declarations are now a denylist, not an entry table."""

    def test_retired_names_are_not_declared_in_registry(self):
        identifiers = {e.identifier for e in reg.ENTRY_POINTS}
        for name in reg.RETIRED_4X_MCP_TOOLS | reg.RETIRED_4X_HTTP_PATHS | reg.RETIRED_4X_ADMIN_ACTIONS:
            assert name not in identifiers, f"retired 4.x identifier '{name}' is declared live"

    def test_retired_tools_are_not_live_mcp_tools(self, live_service):
        live = set(live_service["tool_names"])
        assert not (reg.RETIRED_4X_MCP_TOOLS & live), "a retired 4.x tool became a live MCP tool"
        assert not (reg.RETIRED_4X_ADMIN_ACTIONS & live)

    def test_no_workspace_or_ui_read_models_in_5_0_routers(self, live_service):
        paths = {path for _, path in live_service["http_routes"]}
        for path in paths:
            assert not path.startswith(reg.RETIRED_4X_HTTP_PREFIXES), (
                f"4.x read-model path '{path}' reappeared in a 5.0 router"
            )

    def test_engine_admin_registry_still_resolves_legacy_actions(self):
        """Removing them from the matrix must not break the engine contract."""
        from memory_center.application.admin import build_admin_registry

        registry = build_admin_registry(workspace_file="unused.yaml")
        registered = set(registry.names())
        missing = sorted(reg.RETIRED_4X_ADMIN_ACTIONS - registered)
        assert not missing, f"engine admin registry lost actions: {missing}"
