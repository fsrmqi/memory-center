"""B-01 capability **contract catalog** tests.

The 4.x entry-point declarations (17 HTTP / 4 MCP tool / 14 mc_admin action)
were removed from ``core.foundation.capabilities``. This module now verifies
only the contract data that engine regression tests consume — ``core_fields``
and ``error_semantics`` — and that no entry-point declarations creep back in.

The user-reachable 5.0 surface is a separate, verified registry:
``core.foundation.entry_registry`` / ``tests/entrypoints/test_entry_registry.py``.
"""
from __future__ import annotations

from dataclasses import fields

from memory_center.core.foundation import capabilities
from memory_center.core.foundation.capabilities import (
    CAPABILITIES,
    CAPABILITY_MAP,
    RELATED_5_0_TOOLS,
    Capability,
    all_cli_commands,
)

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


class TestContractCatalog:
    """All 14 required capabilities must be present with complete contracts."""

    def test_all_required_capabilities_present(self):
        for name in REQUIRED_CAPABILITIES:
            assert name in CAPABILITY_MAP, f"Missing capability: {name}"

    def test_each_capability_has_core_fields(self):
        for name in REQUIRED_CAPABILITIES:
            cap = CAPABILITY_MAP[name]
            assert len(cap.core_fields) > 0, f"{name} has no core_fields"

    def test_each_capability_has_error_semantics(self):
        for name in REQUIRED_CAPABILITIES:
            cap = CAPABILITY_MAP[name]
            assert cap.error_semantics, f"{name} has no error_semantics"

    def test_catalog_declares_no_entry_points(self):
        """A contract catalog must not masquerade as an entry-point registry."""
        field_names = {f.name for f in fields(Capability)}
        assert field_names == {"name", "core_fields", "error_semantics"}, (
            f"unexpected Capability fields: {sorted(field_names)}.\n"
            "Step 1: remove any entry-point field from the B-01 contract catalog.\n"
            "Step 2: declare the real 5.0 surface in core.foundation.entry_registry instead."
        )
        for legacy in ("EntryPoint", "entries_by_kind", "all_http_routes",
                       "all_mcp_tools", "all_mcp_admin_actions"):
            assert not hasattr(capabilities, legacy), (
                f"capabilities.py still exports legacy entry helper '{legacy}'"
            )
        assert CAPABILITIES and all(isinstance(c, Capability) for c in CAPABILITIES)

    def test_no_cli_subcommands_in_5_0(self):
        """``memory-center`` has no subcommands; launchers live in the registry."""
        assert all_cli_commands() == []

    def test_related_5_0_tools_point_at_real_tools(self):
        """Related (not equivalent) tools must actually exist in the registry."""
        from memory_center.core.foundation.entry_registry import mcp_tool_names

        live = set(mcp_tool_names())
        for cap_name, tools in RELATED_5_0_TOOLS.items():
            assert cap_name in CAPABILITY_MAP
            assert tools, f"{cap_name} has an empty related-tool list"
            assert set(tools) <= live, f"{cap_name} points at a non-existent tool"
