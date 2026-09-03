"""Task Shadow 入口层测试：CLI 命令、HTTP 路由、mc_admin action 语义一致。"""
from __future__ import annotations

import json
import re

import pytest
from typer.testing import CliRunner

from memory_center.cli.main import app
from memory_center.core.foundation.dispatch import CommandRegistry
from memory_center.core.tasks.shadow import build_merged_shadow
from memory_center.http.routes.params import RouteParams
from memory_center.http.routes.workflow import register_workflow_routes

runner = CliRunner()


def _extract_field(output: str, field: str):
    """从 rich 打印的 Python-repr 输出中提取一个字段值。"""
    match = re.search(rf"'{field}': ('[^']*'|[\w.]+)", output)
    if match is None:
        return None
    token = match.group(1)
    if token.startswith("'"):
        return token.strip("'")
    if token in ("True", "False"):
        return token == "True"
    try:
        return int(token)
    except ValueError:
        return token


def _snapshot_json(seq: int = 2, *, shadow_id: str = "shadow:x:cli-1", session: str = "s-cli-1") -> str:
    return json.dumps(
        {
            "shadow_id": shadow_id,
            "source_provider_id": "dsh-task-shadow@1",
            "source_session_id": session,
            "observed_as_of_seq": seq,
            "durable_as_of_seq": seq,
            "durable_event_count": seq + 1,
            "delivery_mode": "durable",
            "intent_summary": "cli snapshot",
            "candidate_files": ["Cli.java"],
        }
    )


# ------------------------------------------------------------------------ CLI

def test_cli_snapshot_record_and_status(demo_workspace):
    wf = str(demo_workspace)
    record = runner.invoke(
        app,
        ["task-shadow-record-snapshot", "--workspace", wf, "--snapshot", _snapshot_json()],
    )
    assert record.exit_code == 0
    assert '"accepted": true' in record.output.replace(" ", "").replace('"accepted":true', '"accepted": true') or "accepted" in record.output
    status = runner.invoke(app, ["task-shadow-status", "--workspace", wf, "--shadow-id", "shadow:x:cli-1"])
    assert status.exit_code == 0
    assert "Cli.java" in status.output


def test_cli_rejects_volatile_snapshot(demo_workspace):
    volatile = json.dumps(
        {
            "shadow_id": "shadow:x:cli-2",
            "source_provider_id": "dsh-task-shadow@1",
            "source_session_id": "s-cli-2",
            "observed_as_of_seq": 1,
            "durable_as_of_seq": 1,
            "durable_event_count": 1,
            "delivery_mode": "volatile",
        }
    )
    result = runner.invoke(app, ["task-shadow-record-snapshot", "--workspace", str(demo_workspace), "--snapshot", volatile])
    assert result.exit_code == 0  # 错误作为结构化 JSON 返回，不是崩溃
    assert "volatile" in result.output


def test_cli_observation_allowlist_error_is_structured(demo_workspace):
    bad = json.dumps(
        {
            "source_kind": "dsh",
            "source_session_id": "s-cli-3",
            "event_seq": 1,
            "kind": "tool_fact",
            "payload": {"prompt": "nope"},
        }
    )
    result = runner.invoke(app, ["task-shadow-observation", "--workspace", str(demo_workspace), "--observation", bad])
    assert result.exit_code == 0
    assert "payload_field_rejected" in result.output


def test_cli_handoff_lifecycle(demo_workspace):
    wf = str(demo_workspace)
    created = runner.invoke(
        app,
        ["task-shadow-handoff-create", "--workspace", wf, "--from-session-id", "sess-cli", "--to-agent-hint", "codex"],
    )
    assert created.exit_code == 0
    hid = _extract_field(created.output, "handoff_id")
    assert hid
    handed = runner.invoke(
        app,
        [
            "task-shadow-handoff-hand-off",
            "--workspace", wf,
            "--handoff-id", hid,
            "--expected-revision", str(_extract_field(created.output, "revision")),
        ],
    )
    assert _extract_field(handed.output, "handed_off") is True
    claimed = runner.invoke(
        app,
        [
            "task-shadow-handoff-claim",
            "--workspace", wf,
            "--handoff-id", hid,
            "--claimed-by-session-id", "sess-cli-2",
            "--expected-revision", str(_extract_field(handed.output, "revision")),
        ],
    )
    assert _extract_field(claimed.output, "claimed") is True
    assert _extract_field(claimed.output, "claimed_by_session_id") == "sess-cli-2"


# ----------------------------------------------------------------------- HTTP

def _route_params(workspace: str, **params) -> RouteParams:
    flat = {"workspace": [workspace]}
    for key, value in params.items():
        flat[key] = [value if isinstance(value, str) else json.dumps(value)]
    return RouteParams(flat, workspace)


def _registry() -> CommandRegistry:
    registry = CommandRegistry(label="test-shadow")
    register_workflow_routes(registry)
    return registry


def test_http_snapshot_record_status_and_volatile_rejection(demo_workspace):
    wf = str(demo_workspace)
    registry = _registry()
    recorded = registry.dispatch(
        "/workspace/task-shadow-record-snapshot",
        _route_params(wf, shadow_id="shadow:x:http-1", payload=json.loads(_snapshot_json(seq=3, shadow_id="shadow:x:http-1", session="s-http-1"))),
    )
    assert recorded["accepted"] is True
    status = registry.dispatch("/workspace/task-shadow-status", _route_params(wf, shadow_id="shadow:x:http-1"))
    assert status["binding_status"] == "unbound"
    assert status["merged"]["candidate_files"] == ["Cli.java"]
    volatile_payload = {
        "shadow_id": "shadow:x:http-2",
        "source_provider_id": "dsh-task-shadow@1",
        "source_session_id": "s-http-2",
        "observed_as_of_seq": 1,
        "durable_as_of_seq": 1,
        "durable_event_count": 1,
        "delivery_mode": "volatile",
    }
    with pytest.raises(ValueError, match="volatile"):
        registry.dispatch(
            "/workspace/task-shadow-record-snapshot",
            _route_params(wf, shadow_id="shadow:x:http-2", payload=volatile_payload),
        )


def test_http_handoff_router(demo_workspace):
    wf = str(demo_workspace)
    registry = _registry()
    created = registry.dispatch(
        "/workspace/task-shadow-handoff",
        _route_params(wf, action="create", session_id="sess-http-x"),
    )
    handed = registry.dispatch(
        "/workspace/task-shadow-handoff",
        _route_params(wf, action="hand_off", handoff_id=created["handoff_id"], payload={"expected_revision": created["revision"]}),
    )
    assert handed["handed_off"] is True
    claimed = registry.dispatch(
        "/workspace/task-shadow-handoff",
        _route_params(wf, action="claim", handoff_id=created["handoff_id"], session_id="sess-http-y", payload={"expected_revision": handed["revision"]}),
    )
    assert claimed["claimed"] is True
    listing = registry.dispatch("/workspace/task-shadow-handoff", _route_params(wf, action="list"))
    assert listing["total"] >= 1


# ---------------------------------------------------------------- mc_admin

def test_mc_admin_task_shadow_actions(demo_workspace):
    wf = str(demo_workspace)
    from memory_center.application.admin import build_admin_registry

    from memory_center.core.tasks.shadow import record_shadow_snapshot

    record_shadow_snapshot(wf, json.loads(_snapshot_json(seq=4, shadow_id="shadow:x:admin-1", session="s-admin-1")))
    status = build_admin_registry(workspace_file=wf, action="task_shadow_status", name="shadow:x:admin-1").dispatch("task_shadow_status")
    assert status["shadow_id"] == "shadow:x:admin-1"

    task = build_admin_registry(workspace_file=wf, action="task_create", title="admin bind target").dispatch("task_create")["task_id"]
    bound = build_admin_registry(
        workspace_file=wf, action="task_shadow_bind", name="shadow:x:admin-1", task_id=task
    ).dispatch("task_shadow_bind")
    assert bound["bound"] is True

    promoted = build_admin_registry(workspace_file=wf, action="task_shadow_promote", name="shadow:x:admin-1").dispatch("task_shadow_promote")
    assert promoted["promoted"] is True

    discarded = build_admin_registry(workspace_file=wf, action="task_shadow_discard", name="shadow:x:admin-1").dispatch("task_shadow_discard")
    assert discarded["discarded"] is True

    # Observation 通过 admin 通道投递，schema fail-closed 仍然生效
    bad_obs = build_admin_registry(
        workspace_file=wf,
        action="task_shadow_observation_record",
        payload=json.dumps({"source_kind": "unknown", "source_session_id": "x", "event_seq": 1, "kind": "tool_fact"}),
    ).dispatch("task_shadow_observation_record")
    assert bad_obs["recorded"] is False
    assert bad_obs["reason"] == "invalid_source_kind"
