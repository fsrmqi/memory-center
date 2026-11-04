"""case supersede 决策行 + 投影测试（G1：案例替代闭环）。

覆盖：
- supersede_case 追加决策行，不改写既有 case 行，投影把旧 case 判为非 current truth；
- reinstate_case 撤销替代，投影恢复 current truth；
- 未知 case / 重复 supersede / 后继 case 不存在时返回结构化不生效原因；
- 投影遵循"最新决策胜出"，且与旧式存储字段（superseded_by 落在 case 行）兼容。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from memory_center.core.orchestrator.case_decisions import (
    project_case_truth,
    reinstate_case,
    supersede_case,
)
from memory_center.core.orchestrator.write import workspace_record_case
from memory_center.core.storage.workspace import WorkspaceStore


def _seed_case(workspace: Path, task: str) -> str:
    recorded = workspace_record_case(
        str(workspace),
        task,
        ["article-service"],
        ["article-service/src/main/java/com/example/article/Feign.java"],
    )
    return str(recorded["case"]["case_id"])


def _decisions(workspace: Path) -> list[dict]:
    return WorkspaceStore(workspace).read_jsonl("case-decisions.jsonl", limit=10)


def test_supersede_appends_decision_row_and_projects_false(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    case_id = _seed_case(workspace, "ArticleFeignClient 发布迁移")

    result = supersede_case(str(workspace), case_id, actor="maintainer", note="方案被 case-2 取代")

    assert result["superseded"] is True
    assert result["decision_id"]
    # 既有 case 行不被改写（追加式，失败方向安全）
    cases = WorkspaceStore(workspace).read_jsonl("cross-service-task-memory.jsonl", limit=10)
    assert cases[0]["current_truth"] is True
    # 决策行落在新文件，record_type 可识别
    decisions = _decisions(workspace)
    assert len(decisions) == 1
    assert decisions[0]["record_type"] == "case_decision"
    assert decisions[0]["case_id"] == case_id
    assert decisions[0]["decision"] == "supersede"
    # 投影：决策生效后旧 case 不再是 current truth
    projection = project_case_truth(cases, decisions)
    assert projection[case_id] is False


def test_reinstate_restores_projected_truth(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    case_id = _seed_case(workspace, "Feign DTO 兼容改造")

    supersede_case(str(workspace), case_id, actor="maintainer")
    result = reinstate_case(str(workspace), case_id, actor="reviewer", note="替代方案回滚")

    assert result["reinstated"] is True
    cases = WorkspaceStore(workspace).read_jsonl("cross-service-task-memory.jsonl", limit=10)
    projection = project_case_truth(cases, _decisions(workspace))
    assert projection[case_id] is True
    assert len(_decisions(workspace)) == 2


def test_supersede_unknown_case_is_structured_noop(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)

    result = supersede_case(str(workspace), "case-not-exist", actor="maintainer")

    assert result == {"superseded": False, "reason": "case_not_found", "case_id": "case-not-exist"}
    assert _decisions(workspace) == []


def test_repeat_supersede_on_non_truth_case_is_noop(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    case_id = _seed_case(workspace, "MQ consumer 幂等改造")
    supersede_case(str(workspace), case_id, actor="maintainer")

    again = supersede_case(str(workspace), case_id, actor="maintainer")

    assert again["superseded"] is False
    assert again["reason"] == "case_not_current_truth"
    assert len(_decisions(workspace)) == 1


def test_supersede_validates_successor_existence(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    case_id = _seed_case(workspace, "Feign 调用链修复")

    result = supersede_case(str(workspace), case_id, superseded_by="ghost-case", actor="maintainer")

    assert result["superseded"] is False
    assert result["reason"] == "successor_not_found"
    assert _decisions(workspace) == []


def test_projection_respects_legacy_stored_fields(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    # 旧式写法：superseded_by 直接落在 case 行上（仅种子/历史数据会出现）
    workspace_record_case(
        str(workspace),
        "已失效的旧 case",
        ["article-service"],
        ["article-service/src/main/java/com/example/article/Dto.java"],
        superseded_by="case-2",
        current_truth=False,
    )
    live_id = _seed_case(workspace, "仍然有效的 case")

    cases = WorkspaceStore(workspace).read_jsonl("cross-service-task-memory.jsonl", limit=10)
    projection = project_case_truth(cases, [])

    stale = next(c for c in cases if c["task"] == "已失效的旧 case")
    assert projection[stale["case_id"]] is False
    assert projection[live_id] is True


def _seed_finished_session(workspace: Path, intent: str) -> str:
    from memory_center.core.orchestrator.session import (
        workspace_end_session,
        workspace_log_session_event,
        workspace_start_session,
    )

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


def test_consolidate_treats_decision_superseded_conflict_as_add(tmp_path: Path) -> None:
    from memory_center.core.orchestrator.consolidate import workspace_consolidate_sessions
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    case_id = _seed_case(workspace, "ArticleFeignClient 发布迁移")
    supersede_case(str(workspace), case_id, actor="maintainer", note="方案已过时")
    sid = _seed_finished_session(workspace, "ArticleFeignClient 发布迁移")

    result = workspace_consolidate_sessions(str(workspace), [sid])

    candidate = result["candidates"][0]
    assert candidate["operation"] == "ADD"
    assert candidate["expected_write"]["current_truth"] is True


def test_workspace_status_counts_use_projected_truth(tmp_path: Path) -> None:
    from memory_center.core.orchestrator.workspace_ops import workspace_status
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    case_id = _seed_case(workspace, "ArticleFeignClient 发布迁移")

    before = workspace_status(str(workspace))
    assert before["memory_layers"]["L1_case_atoms"]["current_truth_count"] == 1

    supersede_case(str(workspace), case_id, actor="maintainer")

    after = workspace_status(str(workspace))
    l1 = after["memory_layers"]["L1_case_atoms"]
    assert l1["current_truth_count"] == 0
    assert l1["superseded_count"] == 1


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_http_case_supersede_route(tmp_path: Path) -> None:
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


def test_mcp_admin_case_supersede_reinstate_and_list(tmp_path: Path) -> None:
    from memory_center.application.admin import build_admin_registry
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    stale_id = _seed_case(workspace, "ArticleFeignClient 发布迁移")

    reg = build_admin_registry(
        workspace_file=str(workspace), name=stale_id, source="maintainer", reason="方案过时"
    )
    assert reg.dispatch("case_supersede")["superseded"] is True
    assert reg.dispatch("case_reinstate")["reinstated"] is True

    listing = reg.dispatch("case_decision_list")
    assert listing["decision_count"] == 2
    assert all(d["record_type"] == "case_decision" for d in listing["decisions"])


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_cli_case_supersede_and_reinstate_commands(tmp_path: Path) -> None:
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_case_write_http_routes_are_declared_mutating() -> None:
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


def test_supersede_rejects_self_reference(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    case_id = _seed_case(workspace, "ArticleFeignClient 发布迁移")

    result = supersede_case(str(workspace), case_id, superseded_by=case_id, actor="maintainer")

    assert result["superseded"] is False
    assert result["reason"] == "successor_is_self"
    assert _decisions(workspace) == []


def test_supersede_requires_successor_current_truth(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    stale_id = _seed_case(workspace, "旧方案：双写过渡")
    successor_id = _seed_case(workspace, "新方案：直接切换")

    assert supersede_case(str(workspace), successor_id, actor="maintainer")["superseded"] is True

    result = supersede_case(str(workspace), stale_id, superseded_by=successor_id, actor="maintainer")

    assert result["superseded"] is False
    assert result["reason"] == "successor_not_current_truth"
    assert len(_decisions(workspace)) == 1


def test_case_reads_survive_missing_jsonl_export(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    case_id = _seed_case(workspace, "ArticleFeignClient 发布迁移")
    assert supersede_case(str(workspace), case_id, actor="maintainer")["superseded"] is True

    # 模拟 JSONL 导出丢失：SQLite 权威，投影判定不受导出文件缺失影响
    memory_dir = workspace.parent / "memory"
    (memory_dir / "case-decisions.jsonl").unlink()
    (memory_dir / "cross-service-task-memory.jsonl").unlink()

    again = supersede_case(str(workspace), case_id, actor="maintainer")
    assert again["superseded"] is False
    assert again["reason"] == "case_not_current_truth"

    back = reinstate_case(str(workspace), case_id, actor="reviewer")
    assert back["reinstated"] is True


def test_superseded_count_respects_reinstate_projection(tmp_path: Path) -> None:
    from memory_center.core.orchestrator.workspace_ops import workspace_status
    from memory_center.core.storage.workspace import WorkspaceStore
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    WorkspaceStore(workspace).append_jsonl(
        "cross-service-task-memory.jsonl",
        {
            "case_id": "case-legacy-direct",
            "task": "Legacy 直接种子",
            "projects": ["article-service"],
            "files": ["a.java"],
            "current_truth": False,
            "superseded_by": "case-older",
            "created_at": "2026-01-01T00:00:00+00:00",
        },
    )

    assert reinstate_case(str(workspace), "case-legacy-direct", actor="maintainer")["reinstated"] is True

    l1 = workspace_status(str(workspace))["memory_layers"]["L1_case_atoms"]
    assert l1["current_truth_count"] == 1
    assert l1["superseded_count"] == 0
