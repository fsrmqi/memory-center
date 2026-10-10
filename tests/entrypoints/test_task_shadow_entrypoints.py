"""Task Shadow 入口层测试：CLI 命令、HTTP 路由、mc_admin action 语义一致。"""
from __future__ import annotations

import json
import re

import pytest
from typer.testing import CliRunner

pass  # 4.x 入口已退役
pass  # 4.x 入口已退役
pass  # 4.x 入口已退役

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

@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_cli_snapshot_record_and_status(demo_workspace):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_cli_rejects_volatile_snapshot(demo_workspace):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_cli_observation_allowlist_error_is_structured(demo_workspace):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_cli_handoff_lifecycle(demo_workspace):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


# ----------------------------------------------------------------------- HTTP




@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_http_snapshot_record_status_and_volatile_rejection(demo_workspace):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_http_handoff_router(demo_workspace):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


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
