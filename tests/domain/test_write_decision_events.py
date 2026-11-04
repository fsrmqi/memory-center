"""G3 写入决策事件化测试。

验收（docs/WRITE_GOVERNANCE_ABSORPTION_PLAN.md G3）：
- 三条产生 L1 case 的路径（record_case、decide-apply、mc_close 自动记录）
  的 write_receipt 均携带统一 decision 事件（actor / reason / refs）；
- workspace_replay_write_chain 回放能还原完整决策链。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from memory_center.core.orchestrator.case_decisions import supersede_case
from memory_center.core.orchestrator.consolidate import (
    workspace_consolidate_sessions,
    workspace_decide_consolidation_candidate,
)
from memory_center.core.orchestrator.session import (
    workspace_end_session,
    workspace_log_session_event,
    workspace_start_session,
)
from memory_center.core.orchestrator.write import workspace_record_case, workspace_replay_write_chain
from memory_center.core.tasks.receipts import build_write_decision, build_write_receipt


def _seed_case(workspace: Path, task: str) -> str:
    recorded = workspace_record_case(
        str(workspace),
        task,
        ["article-service"],
        ["article-service/src/main/java/com/example/article/Feign.java"],
    )
    return str(recorded["case"]["case_id"])


def _seed_finished_session(workspace: Path, intent: str) -> str:
    started = workspace_start_session(str(workspace), intent)
    sid = str(started["session_id"])
    workspace_log_session_event(
        str(workspace),
        sid,
        "tool_call",
        {
            "tool_name": "mc_lookup",
            "query": "ArticleFeignClient",
            "project": "article-service",
            "file_path": "article-service/src/main/java/com/example/article/Feign.java",
        },
    )
    workspace_end_session(str(workspace), sid, outcome="完成定位", verified_by=["maintainer"])
    return sid


def test_build_write_decision_has_schema_and_fields() -> None:
    decision = build_write_decision(actor="maintainer", reason="方案过时", refs=["case-1"])
    assert decision["schema"]["name"] == "write_decision"
    assert decision["actor"] == "maintainer"
    assert decision["reason"] == "方案过时"
    assert decision["refs"] == ["case-1"]


def test_build_write_receipt_embeds_decision_block() -> None:
    receipt = build_write_receipt(
        layer="L1_case_atoms",
        action="workspace_record_case",
        scope="memory",
        target="cross-service-task-memory.jsonl",
        target_file="memory/cross-service-task-memory.jsonl",
        decision=build_write_decision(actor="maintainer", reason="seeded"),
    )
    assert receipt["decision"]["actor"] == "maintainer"

    bare = build_write_receipt(
        layer="L1_case_atoms",
        action="workspace_record_case",
        scope="memory",
        target="x.jsonl",
        target_file="memory/x.jsonl",
    )
    assert "decision" not in bare


def test_record_case_receipt_carries_decision_event(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    result = workspace_record_case(
        str(workspace),
        "ArticleFeignClient 发布迁移",
        ["article-service"],
        ["article-service/src/main/java/com/example/article/Feign.java"],
        actor="maintainer",
        decision_reason="回放验证种子 case",
    )
    decision = result["write_receipt"]["decision"]
    assert decision["actor"] == "maintainer"
    assert decision["reason"] == "回放验证种子 case"


def test_decide_apply_receipt_carries_reviewer_actor(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    sid = _seed_finished_session(workspace, "MQ consumer 幂等改造")
    staged = workspace_consolidate_sessions(str(workspace), [sid], stage=True)
    candidate_id = staged["staged_candidate_ids"][0]

    applied = workspace_decide_consolidation_candidate(
        str(workspace), candidate_id, decision="approve", actor="reviewer", note="证据复核通过"
    )

    assert applied["applied"] is True
    decision = applied["write_receipt"]["decision"]
    assert decision["actor"] == "reviewer"
    assert decision["reason"] == "证据复核通过"


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_work_close_auto_case_receipt_carries_decision(tmp_path: Path) -> None:
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


def test_replay_write_chain_surfaces_decision_events(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    sid = _seed_finished_session(workspace, "Feign 调用链修复")
    workspace_record_case(
        str(workspace),
        "Feign 调用链修复",
        ["article-service"],
        ["article-service/src/main/java/com/example/article/Feign.java"],
        source_session_id=sid,
        actor="maintainer",
        decision_reason="session 收口记录",
    )
    supersede_case(str(workspace), _find_case_id(workspace, "Feign 调用链修复"), actor="reviewer", note="方案作废")

    replay = workspace_replay_write_chain(str(workspace), session_id=sid)
    session_actors = {row["decision"]["actor"] for row in replay["timeline"] if row.get("decision")}
    assert "maintainer" in session_actors

    # supersede 决策行不带 session 关联，全量回放应覆盖完整决策链
    full_replay = workspace_replay_write_chain(str(workspace))
    full_actors = {row["decision"]["actor"] for row in full_replay["timeline"] if row.get("decision")}
    assert "reviewer" in full_actors


def _find_case_id(workspace: Path, task: str) -> str:
    from memory_center.core.storage.workspace import WorkspaceStore

    rows = WorkspaceStore(workspace).read_jsonl("cross-service-task-memory.jsonl", limit=10)
    return str(next(row["case_id"] for row in rows if row["task"] == task))


def test_mc_close_auto_case_names_its_agent(tmp_path: Path) -> None:
    from memory_center.application.task_shadow_flow import close_case_records
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    sid = _seed_finished_session(workspace, "Feign 调用链修复")

    records = close_case_records(
        str(workspace),
        sid,
        close_task_id="",
        title="",
        auto_sync_mode="balanced",
        outcome="完成定位",
        record_case=True,
        verified_by=["maintainer"],
    )

    recorded = records["recorded"]
    assert recorded and recorded["recorded"] is True
    decision = recorded["write_receipt"]["decision"]
    assert decision["actor"] == "mc_close_agent"
    assert decision["reason"] == "mc_close_auto_case"


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_cli_record_case_passes_actor_to_decision(tmp_path: Path) -> None:
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")
