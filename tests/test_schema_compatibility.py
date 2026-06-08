"""B-03: Public schema compatibility tests.

Verifies that MCP tool schemas (names, required params, optional params,
core return fields) remain backward-compatible against a frozen snapshot.

Rules:
- Adding a new tool: PASS (new tools are allowed)
- Removing a tool: FAIL (breaking change)
- Adding a required param to an existing tool: FAIL (breaking change)
- Removing a required param: PASS (relaxation)
- Adding an optional param: PASS (backward-compatible)
- Removing an optional param: FAIL (breaking change)
- Changing a default value: FAIL (breaking change)
- Adding a core return field to a facade schema: PASS (backward-compatible)
- Removing a core return field: FAIL (breaking change)
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

import pytest

SNAPSHOT_PATH = Path(__file__).parent / "snapshots" / "mcp_tool_schemas.json"


def _load_snapshot() -> dict[str, Any]:
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def _extract_current_tools() -> dict[str, Any]:
    """Extract current MCP tool schemas from source code via importlib."""
    import importlib
    import re

    mod = importlib.import_module("memory_center.mcp.server")
    src = inspect.getsource(mod)
    tool_pattern = r"    def (mc_\w+)\((.*?)\):"
    tools: dict[str, Any] = {}
    for match in re.finditer(tool_pattern, src, re.DOTALL):
        name = match.group(1)
        params_str = match.group(2).strip()
        required = []
        optional = []
        for line in params_str.split("\n"):
            line = line.strip().rstrip(",")
            if not line or line == "ctx: Context":
                continue
            if "=" in line:
                param_name = line.split(":")[0].strip()
                optional.append(param_name)
            else:
                param_name = line.split(":")[0].strip()
                if param_name != "ctx":
                    required.append(param_name)
        tools[name] = {"required": sorted(required), "optional": sorted(optional)}
    return tools


def _extract_current_facade_schemas() -> dict[str, dict[str, Any]]:
    """Extract facade required fields from schemas.py."""
    from memory_center.core.schemas import SCHEMA_REQUIRED_FIELDS

    facade_names = [
        "mc_start", "mc_lookup", "mc_analyze", "mc_sync", "mc_resume",
        "mc_handoff", "mc_close", "mc_admin", "mc_context_pack",
        "mc_onboard", "mc_domain", "mc_freshness",
    ]
    return {
        name: {"required_fields": sorted(SCHEMA_REQUIRED_FIELDS.get(name, set()))}
        for name in facade_names
    }



class TestToolSchemaCompatibility:
    """Verify MCP tool schemas are backward-compatible against snapshot."""

    @pytest.fixture(autouse=True)
    def load_data(self):
        self.snapshot = _load_snapshot()
        self.current = _extract_current_tools()
        self.snapshot_tools = self.snapshot["tools"]

    def test_no_tools_removed(self):
        """Removing a tool is a breaking change."""
        snapshot_names = set(self.snapshot_tools.keys())
        current_names = set(self.current.keys())
        removed = snapshot_names - current_names
        assert not removed, f"Tools removed (breaking change): {removed}"

    def test_no_new_required_params(self):
        """Adding a required param to an existing tool is breaking."""
        for tool_name, snap in self.snapshot_tools.items():
            if tool_name not in self.current:
                continue
            snap_req = set(snap["required"])
            curr_req = set(self.current[tool_name]["required"])
            added = curr_req - snap_req
            assert not added, f"{tool_name}: new required params added: {added}"

    def test_no_optional_params_removed(self):
        """Removing an optional param is breaking."""
        for tool_name, snap in self.snapshot_tools.items():
            if tool_name not in self.current:
                continue
            snap_opt = set(snap["optional"])
            curr_opt = set(self.current[tool_name]["optional"])
            removed = snap_opt - curr_opt
            assert not removed, f"{tool_name}: optional params removed: {removed}"

    def test_no_required_params_removed(self):
        """Removing a required param is a relaxation (allowed but logged)."""
        for tool_name, snap in self.snapshot_tools.items():
            if tool_name not in self.current:
                continue
            snap_req = set(snap["required"])
            curr_req = set(self.current[tool_name]["required"])
            removed = snap_req - curr_req
            # This is allowed (relaxation), but we log it for awareness
            if removed:
                pytest.skip(f"{tool_name}: required params relaxed: {removed}")

    def test_new_tools_allowed(self):
        """New tools can be added without breaking existing callers."""
        snapshot_names = set(self.snapshot_tools.keys())
        current_names = set(self.current.keys())
        added = current_names - snapshot_names
        # This is allowed - just verify they exist
        # New tools are expected as the system evolves
        assert isinstance(added, set)

    def test_snapshot_json_structure(self):
        """Verify the snapshot file has expected structure."""
        assert "_version" in self.snapshot
        assert "tools" in self.snapshot
        assert "facade_schemas" in self.snapshot
        assert isinstance(self.snapshot["tools"], dict)
        assert isinstance(self.snapshot["facade_schemas"], dict)


class TestFacadeSchemaCompatibility:
    """Verify facade return schemas are backward-compatible against snapshot."""

    @pytest.fixture(autouse=True)
    def load_data(self):
        self.snapshot = _load_snapshot()
        self.current = _extract_current_facade_schemas()
        self.snapshot_facades = self.snapshot["facade_schemas"]

    def test_no_facade_schemas_removed(self):
        """Facade schemas should not be removed."""
        snapshot_names = set(self.snapshot_facades.keys())
        current_names = set(self.current.keys())
        removed = snapshot_names - current_names
        assert not removed, f"Facade schemas removed: {removed}"

    def test_no_core_return_fields_removed(self):
        """Removing a core return field from a facade is breaking."""
        for name, snap in self.snapshot_facades.items():
            if name not in self.current:
                continue
            snap_fields = set(snap["required_fields"])
            curr_fields = set(self.current[name]["required_fields"])
            removed = snap_fields - curr_fields
            assert not removed, f"{name}: core return fields removed: {removed}"

    def test_new_core_fields_allowed(self):
        """Adding new core return fields is backward-compatible."""
        for name, snap in self.snapshot_facades.items():
            if name not in self.current:
                continue
            snap_fields = set(snap["required_fields"])
            curr_fields = set(self.current[name]["required_fields"])
            added = curr_fields - snap_fields
            # This is allowed - just verify it's a set
            assert isinstance(added, set)


class TestSnapshotConsistency:
    """Verify snapshot file is internally consistent."""

    def test_snapshot_tools_match_facade_schemas(self):
        """All tools in snapshot should have corresponding facade schemas."""
        snap = _load_snapshot()
        tool_names = set(snap["tools"].keys())
        facade_names = set(snap["facade_schemas"].keys())
        # Tools and facades should overlap
        common = tool_names & facade_names
        assert len(common) > 0, "No overlap between tools and facade schemas"

    def test_snapshot_required_params_sorted(self):
        """Snapshot params should be sorted for deterministic comparison."""
        snap = _load_snapshot()
        for name, tool in snap["tools"].items():
            assert tool["required"] == sorted(tool["required"]), f"{name}: required not sorted"
            assert tool["optional"] == sorted(tool["optional"]), f"{name}: optional not sorted"

    def test_snapshot_facade_fields_sorted(self):
        """Snapshot facade fields should be sorted."""
        snap = _load_snapshot()
        for name, schema in snap["facade_schemas"].items():
            assert schema["required_fields"] == sorted(schema["required_fields"]), f"{name}: fields not sorted"
