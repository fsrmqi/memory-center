"""consolidate-session 测试：多会话 → L1 case / L3 记忆块候选整合。

覆盖：
- 默认 dry-run，不写盘；
- 无冲突会话产生 ADD 候选，含 source_refs / evidence_refs / expected_write；
- 与既有 current-truth case 或同批重复会话冲突时产生 REVIEW；已失效 case 不阻止 ADD；
- apply=True 时只写入 ADD，REVIEW 不写；
- include_l3 产出 L3 memory-block 草稿候选；
- 未知 session 进入 skipped。
"""
from __future__ import annotations

from pathlib import Path

from memory_center.core.orchestrator.consolidate import (
    workspace_consolidate_sessions,
    workspace_decide_consolidation_candidate,
    workspace_list_consolidation_candidates,
)
from memory_center.core.orchestrator.session import (
    workspace_end_session,
    workspace_log_session_event,
    workspace_start_session,
)
from memory_center.core.orchestrator.write import workspace_record_case


def _seed_finished_session(workspace: Path, intent: str, session_id: str | None = None) -> str:
    from tests.fixtures import setup_demo_workspace  # noqa: F401 (keeps fixture usage uniform)

    started = workspace_start_session(str(workspace), intent, session_id=session_id)
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


def test_consolidate_dry_run_produces_add_candidates(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    sid = _seed_finished_session(workspace, "ArticleFeignClient 发布迁移")

    result = workspace_consolidate_sessions(str(workspace), [sid])

    assert result["dry_run"] is True
    assert result["applied"] is False
    assert result["candidate_count"] == 1
    candidate = result["candidates"][0]
    assert candidate["session_id"] == sid
    assert candidate["operation"] in {"ADD", "REVIEW"}
    assert candidate["reason"]
    assert candidate["expected_write"]["layer"] == "L1_case_atoms"
    # 候选必须带来源引用与证据引用
    assert "source_refs" in candidate
    assert "evidence_refs" in candidate
    assert candidate["draft_case"]["memory_layer"] == "L1_case_atom"
    # dry-run 不产生写回执
    assert "write_receipt" not in candidate


def test_consolidate_requires_review_when_current_truth_conflict(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    # 先写入一条 current truth case
    workspace_record_case(
        str(workspace),
        "ArticleFeignClient 发布迁移",
        ["article-service"],
        ["article-service/src/main/java/com/example/article/Feign.java"],
        current_truth=True,
    )
    sid = _seed_finished_session(workspace, "ArticleFeignClient 发布迁移")

    result = workspace_consolidate_sessions(str(workspace), [sid])

    candidate = result["candidates"][0]
    assert candidate["operation"] == "REVIEW"
    assert candidate["conflicts"], "应检测到既有冲突 case"
    assert candidate["expected_write"]["action"] == "review_required"


def test_consolidate_adds_current_truth_when_conflict_is_stale(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    # 已失效的既有 case（superseded_by 已设）
    workspace_record_case(
        str(workspace),
        "ArticleFeignClient 发布迁移",
        ["article-service"],
        ["article-service/src/main/java/com/example/article/Feign.java"],
        superseded_by="case-2",
        current_truth=False,
    )
    sid = _seed_finished_session(workspace, "ArticleFeignClient 发布迁移")

    result = workspace_consolidate_sessions(str(workspace), [sid])

    candidate = result["candidates"][0]
    assert candidate["operation"] == "ADD"
    assert candidate["expected_write"]["current_truth"] is True

    applied = workspace_consolidate_sessions(str(workspace), [sid], apply=True)
    from memory_center.core.storage.workspace import WorkspaceStore

    cases = WorkspaceStore(workspace).read_jsonl("cross-service-task-memory.jsonl", limit=10)
    assert applied["summary"]["applied_count"] == 1
    assert cases[-1]["current_truth"] is True
    assert cases[-1]["superseded_by"] == ""


def test_consolidate_apply_writes_only_add(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    # 一条冲突 current truth → REVIEW；一条新会话 → ADD
    workspace_record_case(
        str(workspace),
        "Feign DTO 兼容改造",
        ["article-service"],
        ["article-service/src/main/java/com/example/article/Dto.java"],
        current_truth=True,
    )
    review_sid = _seed_finished_session(workspace, "Feign DTO 兼容改造")
    add_sid = _seed_finished_session(workspace, "MQ consumer 幂等改造")

    result = workspace_consolidate_sessions(str(workspace), [review_sid, add_sid], apply=True)

    assert result["applied"] is True
    ops = {c["session_id"]: c["operation"] for c in result["candidates"]}
    assert ops[review_sid] == "REVIEW"
    assert ops[add_sid] == "ADD"
    # REVIEW 不写回执，ADD 写回执
    by_sid = {c["session_id"]: c for c in result["candidates"]}
    assert by_sid[review_sid].get("write_receipt") is None
    assert by_sid[add_sid].get("write_receipt") is not None
    # 写入后再次 consolidate 应要求 REVIEW
    result2 = workspace_consolidate_sessions(str(workspace), [add_sid])
    assert result2["candidates"][0]["operation"] == "REVIEW"


def test_consolidate_skips_unfinished_and_batch_duplicates(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    started = workspace_start_session(str(workspace), "未结束的 Feign 改造")
    unfinished_id = str(started["session_id"])
    first_id = _seed_finished_session(workspace, "同批 Feign 改造")
    second_id = _seed_finished_session(workspace, "同批 Feign 改造")

    result = workspace_consolidate_sessions(str(workspace), [unfinished_id, first_id, second_id], apply=True)

    assert result["skipped"] == [{"session_id": unfinished_id, "reason": "session_not_finished"}]
    by_sid = {candidate["session_id"]: candidate for candidate in result["candidates"]}
    assert by_sid[first_id]["operation"] == "ADD"
    assert by_sid[second_id]["operation"] == "REVIEW"
    assert by_sid[second_id].get("write_receipt") is None
    assert result["summary"]["applied_count"] == 1


def test_staged_candidate_requires_explicit_approval_before_l1_write(tmp_path: Path) -> None:
    from memory_center.core.storage.workspace import WorkspaceStore
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    session_id = _seed_finished_session(workspace, "已验证的 MQ 幂等处理")

    staged = workspace_consolidate_sessions(str(workspace), [session_id], stage=True)
    candidate_id = staged["staged_candidate_ids"][0]
    assert staged["dry_run"] is False
    assert staged["staged"] is True
    assert WorkspaceStore(workspace).read_jsonl("cross-service-task-memory.jsonl", limit=10) == []

    pending = workspace_list_consolidation_candidates(str(workspace))
    assert pending["candidate_count"] == 1
    assert pending["candidates"][0]["candidate_id"] == candidate_id
    assert pending["candidates"][0]["lifecycle"] == "pending"

    approved = workspace_decide_consolidation_candidate(
        str(workspace), candidate_id, decision="approve", actor="maintainer", note="evidence reviewed"
    )
    assert approved["applied"] is True
    assert approved["write_receipt"]
    applied = workspace_list_consolidation_candidates(str(workspace), status="applied")
    assert applied["candidate_count"] == 1
    assert applied["candidates"][0]["lifecycle"] == "applied"
    assert len(WorkspaceStore(workspace).read_jsonl("cross-service-task-memory.jsonl", limit=10)) == 1


def test_staged_review_candidate_cannot_be_approved_and_can_be_rejected(tmp_path: Path) -> None:
    from memory_center.core.storage.workspace import WorkspaceStore
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    workspace_record_case(
        str(workspace), "已有 Feign 契约", ["article-service"], ["article-service/src/main/java/com/example/article/Feign.java"]
    )
    session_id = _seed_finished_session(workspace, "已有 Feign 契约")
    staged = workspace_consolidate_sessions(str(workspace), [session_id], stage=True)
    candidate_id = staged["staged_candidate_ids"][0]

    blocked = workspace_decide_consolidation_candidate(str(workspace), candidate_id, decision="approve", actor="maintainer")
    assert blocked["applied"] is False
    assert blocked["reason"] == "candidate_requires_manual_resolution"
    rejected = workspace_decide_consolidation_candidate(str(workspace), candidate_id, decision="reject", actor="maintainer")
    assert rejected["rejected"] is True
    assert workspace_list_consolidation_candidates(str(workspace), status="rejected")["candidate_count"] == 1
    assert len(WorkspaceStore(workspace).read_jsonl("cross-service-task-memory.jsonl", limit=10)) == 1


def test_consolidate_include_l3_emits_block_draft(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    sid = _seed_finished_session(workspace, "团队规范：Feign 契约变更需评审")

    result = workspace_consolidate_sessions(str(workspace), [sid], include_l3=True)

    candidate = result["candidates"][0]
    l3 = candidate.get("l3_draft")
    assert l3 is not None
    assert l3["block_key"] in {"team_rules", "workspace_profile", "architecture_invariants", "active_migration_policy"}
    assert l3["file"]
    assert l3["draft_entry"]
    assert "source session" in l3["draft_entry"]


def test_consolidate_defaults_to_recent_sessions_and_skips_unknown(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    _seed_finished_session(workspace, "Feign 调用链修复")

    # 不传 session_id：默认取最近会话
    result = workspace_consolidate_sessions(str(workspace), limit=5)
    assert result["candidate_count"] >= 1

    # 未知 session 进入 skipped
    result2 = workspace_consolidate_sessions(str(workspace), ["session-not-exist"])
    assert result2["candidate_count"] == 0
    assert result2["skipped_count"] == 1
    assert result2["skipped"][0]["reason"] == "session_not_found"
