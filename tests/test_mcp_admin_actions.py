"""Direct unit tests for the mc_admin action registry.

These tests bypass FastMCP and the ``create_server`` factory so we can verify
that the registry built by ``admin_actions.build_admin_registry`` exposes the
expected action set and dispatches each handler without crashing on a fresh
demo workspace.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from memory_center.application.admin import (
    build_admin_registry,
    explanation_action,
    metrics_summary_action,
    parse_payload,
)
from memory_center.core.tasks.artifacts import create_task_space


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
        "task_health",
        "task_health_all",
        "task_repair_plan",
        "task_repair_apply",
        "task_resume_check",
        "session_recent",
        "write_judge",
        "eval_agent_guidance",
        "eval_agent_guidance_adoption",
        "eval_agent_guidance_adoption_trend",
        "eval_agent_guidance_replay",
        "eval_agent_guidance_replay_trend",
        "eval_java_call_resolution_unresolved",
        "eval_agent_guidance_trend",
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
    assert out.get("persona") == "developer"


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


def test_task_health_actions_dispatch_through_registry(tmp_path: Path) -> None:
    from tests.fixtures import setup_demo_workspace

    wf = str(setup_demo_workspace(tmp_path))
    task = create_task_space(wf, title="MCP task health")
    reg = build_admin_registry(workspace_file=wf, task_id=task["task_id"], limit=5)

    health = reg.dispatch("task_health")
    assert health["task_id"] == task["task_id"]
    assert "issues" in health
    assert "repair_suggestions" in health

    all_health = reg.dispatch("task_health_all")
    assert all_health["checked"] >= 1
    assert "health_counts" in all_health

    repair = reg.dispatch("task_repair_plan")
    assert repair["task_id"] == task["task_id"]
    assert repair["apply_supported"] is False
    assert "repair_plan" in repair

    repair_apply = reg.dispatch("task_repair_apply")
    assert repair_apply["dry_run"] is True
    assert repair_apply["applied"] is False
    assert "execution_plan" in repair_apply

    resume_check = reg.dispatch("task_resume_check")
    assert resume_check["workflow"] == "task-resume-check"
    assert resume_check["task_id"] == task["task_id"]
    assert "recommended_next_step" in resume_check
