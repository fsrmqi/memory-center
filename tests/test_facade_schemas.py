"""B-02: Facade core return type schema tests.

Validates that the 12 facade return types defined in schemas.py:
1. Are registered in both SCHEMA_VERSIONS and SCHEMA_REQUIRED_FIELDS
2. Pass validate_schema_payload with minimal valid payloads
3. Fail when required fields are missing
4. Backward-compatible: existing pre-B-02 schemas still work
5. mc_admin has empty required fields (flexible dispatch)
"""
from __future__ import annotations

import inspect

import pytest

from memory_center.core.foundation.schemas import (
    SCHEMA_REQUIRED_FIELDS,
    SCHEMA_VERSIONS,
    schema_meta,
    validate_schema_payload,
    with_schema,
)

# ---------------------------------------------------------------------------
# 1. All 12 facades are registered
# ---------------------------------------------------------------------------

FACADE_NAMES = [
    "mc_start",
    "mc_lookup",
    "mc_analyze",
    "mc_sync",
    "mc_resume",
    "mc_handoff",
    "mc_close",
    "mc_admin",
    "mc_context_pack",
    "mc_onboard",
    "mc_domain",
    "mc_freshness",
]


class TestFacadeSchemaRegistration:
    """Every facade must have a version and required-field entry."""

    def test_all_facades_in_schema_versions(self):
        for name in FACADE_NAMES:
            assert name in SCHEMA_VERSIONS, f"{name} missing from SCHEMA_VERSIONS"

    def test_all_facades_in_required_fields(self):
        for name in FACADE_NAMES:
            assert name in SCHEMA_REQUIRED_FIELDS, f"{name} missing from SCHEMA_REQUIRED_FIELDS"

    def test_all_facades_version_is_1(self):
        for name in FACADE_NAMES:
            assert SCHEMA_VERSIONS[name] == 1, f"{name} version should be 1 at initial registration"


# ---------------------------------------------------------------------------
# 2. schema_meta works for facades
# ---------------------------------------------------------------------------

class TestSchemaMeta:
    def test_meta_contains_name_and_version(self):
        for name in FACADE_NAMES:
            meta = schema_meta(name)
            assert meta["name"] == name
            assert meta["version"] == 1

    def test_unknown_schema_returns_version_1_default(self):
        meta = schema_meta("nonexistent_schema_xyz")
        assert meta["version"] == 1


# ---------------------------------------------------------------------------
# 3. validate_schema_payload: valid payloads pass
# ---------------------------------------------------------------------------

VALID_PAYLOADS = {
    "mc_start": {"workflow": "mc-start", "sniff": {"a": 1}, "session": {"b": 2}},
    "mc_lookup": {"result": {"hits": []}},
    "mc_analyze": {"workflow": "mc-analyze", "depth": "quick", "impact": {}},
    "mc_sync": {"workflow": "mc-sync", "mode": "sniff", "result": {}},
    "mc_resume": {"workflow": "mc-resume", "resume_packet": {}, "next_actions": [], "unresolved_items": [], "recent_evidence": []},
    "mc_handoff": {"workflow": "mc-handoff", "handoff_packet": {}, "recent_evidence": [], "tool_usage_report": {}},
    "mc_close": {"workflow": "mc-close", "ended": {}, "sync_case": {}, "suggested_case": {}},
    "mc_admin": {"action": "status", "data": {}},
    "mc_context_pack": {"workflow": "mc-context-pack", "query": "test", "intent": "auto", "entrypoints": [], "relationships": [], "checklist": []},
    "mc_onboard": {"workflow": "mc-onboard", "tour": {}},
    "mc_domain": {"workflow": "mc-domain", "domains": [], "domain_count": 0},
    "mc_freshness": {"workflow": "mc-freshness"},
}


class TestValidPayloads:
    def test_valid_payload_passes(self):
        for name, payload in VALID_PAYLOADS.items():
            validate_schema_payload(name, payload)  # should not raise

    def test_with_schema_wraps_meta(self):
        for name, payload in VALID_PAYLOADS.items():
            result = with_schema(name, payload)
            assert "schema" in result
            assert result["schema"]["name"] == name
            # All original keys still present
            for key in payload:
                assert key in result


# ---------------------------------------------------------------------------
# 4. validate_schema_payload: missing required fields raise ValueError
# ---------------------------------------------------------------------------

class TestMissingRequiredFields:
    def test_missing_workflow_raises(self):
        """Most facades require 'workflow'; removing it should fail."""
        for name in ["mc_start", "mc_analyze", "mc_sync", "mc_resume",
                      "mc_handoff", "mc_close", "mc_context_pack",
                      "mc_onboard", "mc_domain", "mc_freshness"]:
            required = SCHEMA_REQUIRED_FIELDS[name]
            if "workflow" not in required:
                continue
            payload = {k: {} for k in required if k != "workflow"}
            with pytest.raises(ValueError, match="missing required fields"):
                validate_schema_payload(name, payload)

    def test_mc_admin_empty_required_never_raises(self):
        """mc_admin has no required fields, so any payload should pass."""
        validate_schema_payload("mc_admin", {})
        validate_schema_payload("mc_admin", {"action": "status"})

    def test_each_facade_missing_single_field_raises(self):
        """For each facade with required fields, removing one should fail."""
        for name in FACADE_NAMES:
            required = SCHEMA_REQUIRED_FIELDS[name]
            if not required:
                continue
            # Remove one required field
            missing_field = next(iter(required))
            payload = {k: "x" for k in required if k != missing_field}
            with pytest.raises(ValueError, match="missing required fields"):
                validate_schema_payload(name, payload)


# ---------------------------------------------------------------------------
# 5. Backward compatibility: pre-B-02 schemas still work
# ---------------------------------------------------------------------------

LEGACY_SCHEMAS = [
    "write_receipt",
    "timeline_item",
    "timeline_result",
    "eval_result",
    "resume_packet",
    "handoff_packet",
    "workspace_continuity_dashboard",
    "workspace_dashboard",
    "lookup_hint",
    "tool_usage_report",
    "memory_ref",
    "memory_ref_batch",
]


class TestBackwardCompatibility:
    def test_legacy_schemas_still_registered(self):
        for name in LEGACY_SCHEMAS:
            assert name in SCHEMA_VERSIONS, f"Legacy schema {name} removed from SCHEMA_VERSIONS"
            assert name in SCHEMA_REQUIRED_FIELDS, f"Legacy schema {name} removed from SCHEMA_REQUIRED_FIELDS"

    def test_legacy_version_unchanged(self):
        for name in LEGACY_SCHEMAS:
            assert SCHEMA_VERSIONS[name] == 1, f"Legacy schema {name} version changed"


# ---------------------------------------------------------------------------
# 6. Source-code level: MCP server returns match required fields
# ---------------------------------------------------------------------------

class TestMCPReturnConsistency:
    """Verify that MCP server return statements include the required fields."""

    def test_mc_start_returns_workflow_sniff_session(self):
        import memory_center.application.task_start as mcp_mod
        src = inspect.getsource(mcp_mod)
        assert '"workflow": "mc-start"' in src
        assert '"sniff":' in src
        assert '"session":' in src

    def test_mc_analyze_returns_workflow_depth_impact(self):
        import memory_center.mcp.server as mcp_mod
        src = inspect.getsource(mcp_mod)
        assert '"workflow": "mc-analyze"' in src
        assert '"depth": depth' in src
        assert '"impact":' in src

    def test_mc_resume_returns_all_required(self):
        import memory_center.mcp.server as mcp_mod
        src = inspect.getsource(mcp_mod)
        assert '"workflow": "mc-resume"' in src
        assert '"resume_packet":' in src
        assert '"next_actions":' in src
        assert '"unresolved_items":' in src
        assert '"recent_evidence":' in src

    def test_mc_handoff_returns_all_required(self):
        import memory_center.mcp.server as mcp_mod
        src = inspect.getsource(mcp_mod)
        assert '"workflow": "mc-handoff"' in src
        assert '"handoff_packet":' in src
        assert '"recent_evidence":' in src
        assert '"tool_usage_report":' in src

    def test_mc_close_returns_all_required(self):
        import memory_center.mcp.server as mcp_mod
        src = inspect.getsource(mcp_mod)
        assert '"workflow": "mc-close"' in src
        assert '"ended":' in src
        assert '"sync_case":' in src
        assert '"suggested_case":' in src

    def test_mc_context_pack_returns_all_required(self):
        import memory_center.mcp.server as mcp_mod
        from memory_center.application import analysis

        src = inspect.getsource(mcp_mod)
        app_src = inspect.getsource(analysis.build_context_pack)
        assert '"workflow": "mc-context-pack"' in src
        for field in ("query", "intent", "entrypoints", "relationships", "checklist"):
            assert field in app_src

    def test_mc_onboard_returns_workflow_tour(self):
        import memory_center.mcp.server as mcp_mod
        from memory_center.application import analysis

        src = inspect.getsource(mcp_mod)
        app_src = inspect.getsource(analysis.onboarding_tour)
        assert '"workflow": "mc-onboard"' in src
        assert '"tour"' in app_src

    def test_mc_domain_returns_workflow_domains_domain_count(self):
        import memory_center.mcp.server as mcp_mod
        from memory_center.application import analysis

        src = inspect.getsource(mcp_mod)
        app_src = inspect.getsource(analysis.domain_overview)
        assert '"workflow": "mc-domain"' in src
        assert '"domains"' in app_src
        assert '"domain_count"' in app_src

    def test_mc_freshness_returns_workflow(self):
        import memory_center.mcp.server as mcp_mod
        src = inspect.getsource(mcp_mod)
        assert '"workflow": "mc-freshness"' in src
