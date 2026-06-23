"""Direct unit tests for the mc_admin action registry.

These tests bypass FastMCP and the ``create_server`` factory so we can verify
that the registry built by ``admin_actions.build_admin_registry`` exposes the
expected action set and dispatches each handler without crashing on a fresh
demo workspace.
"""

from __future__ import annotations


import pytest

from memory_center.mcp.admin_actions import (
    build_admin_registry,
    explanation_action,
    metrics_summary_action,
    parse_payload,
)


def test_build_admin_registry_lists_known_actions() -> None:
    reg = build_admin_registry(workspace_file="/tmp/does-not-exist")
    names = set(reg.names())
    # Spot-check some critical actions across functional groups.
    expected = {
        "status",
        "dashboard",
        "audit",
        "drill_ref",
        "drill_timeline",
        "task_list",
        "session_recent",
        "write_judge",
        "eval_regression_suite",
        "eval_golden",
        "method_walkthrough",
        "metrics_summary",
        "regression_alerts",
        "verification_loop",
        "explanation",
    }
    missing = expected - names
    assert not missing, f"missing actions: {missing}"


def test_unknown_action_raises_with_valid_names() -> None:
    reg = build_admin_registry(workspace_file="/tmp/does-not-exist")
    with pytest.raises(ValueError) as exc:
        reg.dispatch("definitely_not_a_real_action")
    msg = str(exc.value)
    assert "Unknown" in msg and "definitely_not_a_real_action" in msg
    assert "Valid" in msg


def test_metrics_summary_action_is_pure() -> None:
    payload = metrics_summary_action()
    assert payload.get("workflow") == "mc-metrics"
    assert "summary" in payload


def test_explanation_action_uses_persona() -> None:
    out = explanation_action("hello", persona="developer")
    assert "explanation" in out
    inner = out["explanation"]
    assert inner.get("persona") == "developer"


def test_parse_payload_handles_json_and_plain_text() -> None:
    assert parse_payload("") is None
    assert parse_payload("{\"a\": 1}") == {"a": 1}
    fallback = parse_payload("not-json")
    assert fallback == {"raw": "not-json"}


def test_metrics_action_dispatch_through_registry() -> None:
    reg = build_admin_registry(workspace_file="/tmp/mc-admin-registry-test", name="query_latency")
    payload = reg.dispatch("metrics_summary")
    assert payload.get("workflow") == "mc-metrics"
    assert payload["summary"]["metric"] == "query_latency"
    assert payload["summary"]["count"] == 0
