"""case schema 化与字段级合并算子测试(设计参考 OpenViking merge_op/MemoryTypeSchema)。

覆盖:
- merge_ops:immutable/replace/append/sum/patch 全算子纪律与失败路径;
- SEARCH/REPLACE 块解析、行级匹配、失配保守报错;
- case_schema:内置注册、workspace YAML 覆盖、required/类型/三段式校验;
- record_case:extra_fields 入库 + schema_validation 返回;
- suggest_case:附带写作指南(无 LLM);
- consolidation approve:同主题失效 case 的 append/sum 字段并入候选。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from memory_center.core.foundation.merge_ops import (
    MergeOp,
    MergeOpError,
    apply_merge_op,
    apply_str_patch,
    merge_case_record,
    parse_str_patch,
)
from memory_center.core.knowledge.case_schema import (
    BUILTIN_CASE_SCHEMA,
    CASE_SCHEMA_FILENAME,
    case_field_ops,
    case_writing_guide,
    load_case_registry,
    validate_case_draft,
)
from memory_center.core.orchestrator.consolidate import (
    workspace_consolidate_sessions,
    workspace_decide_consolidation_candidate,
)
from memory_center.core.orchestrator.session import (
    workspace_end_session,
    workspace_log_session_event,
    workspace_suggest_case,
    workspace_start_session,
)
from memory_center.core.orchestrator.write import workspace_record_case
from memory_center.core.storage.workspace import WorkspaceStore


# ---------- merge_ops ----------


def test_immutable_op_rejects_change_and_allows_same() -> None:
    assert apply_merge_op(MergeOp.IMMUTABLE, "task", "same", "same") == "same"
    assert apply_merge_op(MergeOp.IMMUTABLE, "task", "v", None) == "v"
    with pytest.raises(MergeOpError):
        apply_merge_op(MergeOp.IMMUTABLE, "task", "old", "new")


def test_replace_and_append_ops() -> None:
    assert apply_merge_op(MergeOp.REPLACE, "flow", "old", "new") == "new"
    assert apply_merge_op(MergeOp.APPEND, "projects", ["a"], ["a", "b"]) == ["a", "b"]
    assert apply_merge_op(MergeOp.APPEND, "projects", ["a"], None) == ["a"]
    assert apply_merge_op(MergeOp.APPEND, "note", "line1", "line2") == "line1\nline2"
    # 字符串 append 幂等:同内容不重复
    assert apply_merge_op(MergeOp.APPEND, "note", "line1", "line1") == "line1"


def test_sum_op_accumulates_and_tolerates_invalid() -> None:
    assert apply_merge_op(MergeOp.SUM, "executions", 3, 2) == 5
    assert apply_merge_op(MergeOp.SUM, "executions", 1, None) == 1
    assert apply_merge_op(MergeOp.SUM, "executions", 3, "bad") == 3


def test_patch_blocks_apply_and_fail_conservatively() -> None:
    patch = parse_str_patch("<<<<<<< SEARCH\nold line\n=======REPLACE=======\nnew line\n>>>>>>> END")
    assert len(patch.blocks) == 1
    assert apply_str_patch("prefix old line suffix", patch) == "prefix new line suffix"
    assert apply_str_patch("a\nold line\nb", patch) == "a\nnew line\nb"
    with pytest.raises(MergeOpError):
        apply_str_patch("nothing matches", patch)


def test_merge_case_record_respects_schema_ops() -> None:
    schema = {"task": "immutable", "flow": "replace", "projects": "append", "executions": "sum"}
    base = {"task": "T", "flow": "a->b", "projects": ["p1"], "executions": 1}
    merged = merge_case_record(base, {"flow": "a->b->c", "projects": ["p2"], "executions": 1}, schema)
    assert merged["task"] == "T"
    assert merged["flow"] == "a->b->c"
    assert merged["projects"] == ["p1", "p2"]
    assert merged["executions"] == 2
    with pytest.raises(MergeOpError):
        merge_case_record(base, {"task": "X"}, schema)


# ---------- case_schema ----------


def _seed_session(workspace: Path, intent: str, verified: bool = True) -> str:
    sid = str(workspace_start_session(str(workspace), intent)["session_id"])
    workspace_log_session_event(str(workspace), sid, "tool_call", {"tool_name": "mc_analyze", "query": "MoveArticleRequest"})
    workspace_end_session(str(workspace), sid, outcome="完成", verified_by=["maintainer"] if verified else [])
    return sid


def test_builtin_registry_and_workspace_override(demo_workspace: Path) -> None:
    registry = load_case_registry(WorkspaceStore(demo_workspace))
    assert registry.get().case_type == BUILTIN_CASE_SCHEMA.case_type
    assert "task" in case_field_ops(registry.get())

    override = (
        "schemas:\n"
        "  - case_type: custom_case\n"
        "    description: 团队自定义\n"
        "    fields:\n"
        "      - name: task\n"
        "        type: string\n"
        "        op: immutable\n"
        "        required: true\n"
        "      - name: review_count\n"
        "        type: int\n"
        "        op: sum\n"
    )
    (WorkspaceStore(demo_workspace).rules_dir / CASE_SCHEMA_FILENAME).write_text(override, encoding="utf-8")
    registry2 = load_case_registry(WorkspaceStore(demo_workspace))
    assert "custom_case" in registry2.list_types()
    custom = registry2.get("custom_case")
    ops = case_field_ops(custom)
    assert ops["task"] == "immutable"
    assert ops["review_count"] == "sum"


def test_validate_case_draft_enforces_required_and_sections() -> None:
    schema = BUILTIN_CASE_SCHEMA
    good = {
        "task": "T",
        "projects": ["p"],
        "situation": "## Situation\n条件",
        "approach": "## Approach\n步骤",
        "reflect": "## Reflect\n禁令",
    }
    assert validate_case_draft(good, schema)["valid"] is True

    missing = {key: value for key, value in good.items() if key != "task"}
    result = validate_case_draft(missing, schema)
    assert result["valid"] is False
    assert any("task" in error for error in result["errors"])

    bad_section = {**good, "situation": "没有段落头"}
    result = validate_case_draft(bad_section, schema)
    assert any("Situation" in error for error in result["errors"])

    oversized = {**good, "approach": "## Approach\n" + "x" * 4000}
    result = validate_case_draft(oversized, schema)
    assert result["valid"] is True  # 长度是 warning 不是 error
    assert result["warnings"]


def test_writing_guide_shape() -> None:
    guide = case_writing_guide(BUILTIN_CASE_SCHEMA, include_template=False)
    assert guide["case_type"] == BUILTIN_CASE_SCHEMA.case_type
    assert len(guide["writing_rules"]) >= 4
    assert all({"name", "type", "op", "required", "description"} == set(item) for item in guide["fields"])


# ---------- 接入点 ----------


def test_record_case_accepts_extra_fields_and_returns_validation(demo_workspace: Path) -> None:
    result = workspace_record_case(
        str(demo_workspace),
        task="Feign DTO 兼容改造",
        projects=["common-api"],
        files=["a.java"],
        extra_fields={
            "situation": "## Situation\n增加可选字段",
            "approach": "## Approach\n给默认值",
            "reflect": "## Reflect\n禁止删旧字段",
            "executions": 2,
        },
    )
    assert result["recorded"] is True
    assert result["schema_validation"]["valid"] is True
    stored = WorkspaceStore(demo_workspace).read_jsonl_prefer_backend("cross-service-task-memory.jsonl", limit=5)[-1]
    assert stored["situation"].startswith("## Situation")
    assert stored["executions"] == 2


def test_record_case_unknown_extra_fields_are_dropped(demo_workspace: Path) -> None:
    result = workspace_record_case(
        str(demo_workspace),
        task="未知字段过滤",
        projects=["p"],
        files=[],
        extra_fields={"not_in_schema": "should be dropped", "executions": 1},
    )
    case = result["case"]
    assert "not_in_schema" not in case
    assert case["executions"] == 1


def test_suggest_case_includes_writing_guide(demo_workspace: Path) -> None:
    sid = _seed_session(demo_workspace, "Feign DTO 兼容改造")
    result = workspace_suggest_case(str(demo_workspace), sid)
    guide = result.get("case_writing_guide") or {}
    assert guide.get("case_type") == BUILTIN_CASE_SCHEMA.case_type
    assert guide.get("fields")
    assert guide.get("content_template")


def _stage_candidate(workspace: Path, intent: str) -> tuple[str, str]:
    sid = _seed_session(workspace, intent)
    result = workspace_consolidate_sessions(str(workspace), [sid], stage=True)
    candidate = result["candidates"][0]
    return str(candidate["candidate_id"]), sid


def test_approve_merges_append_sum_fields_from_superseded_cases(demo_workspace: Path) -> None:
    workspace = str(demo_workspace)
    # 种子 case 的 projects/files 与后续候选 session 事件一致,保证相似度过阈值;
    # valid_to 让这条 case 成为"同主题失效 case"(current_truth=False),从而触发合并。
    workspace_record_case(
        workspace,
        task="Feign DTO 兼容改造",
        projects=["common-api"],
        files=["common-api/src/main/java/Feign.java"],
        risk_points=["契约兼容"],
        verified_by=["alice"],
        extra_fields={"executions": 3, "successes": 2},
        valid_to="2026-01-01T00:00:00+00:00",
    )
    workspace_record_case(
        workspace,
        task="Feign DTO 兼容改造",
        projects=["common-api"],
        files=["common-api/src/main/java/Feign.java"],
        risk_points=["灰度兼容"],
        verified_by=["carol"],
        extra_fields={"executions": 5, "successes": 4},
        valid_to="2026-01-02T00:00:00+00:00",
    )

    sid = str(workspace_start_session(demo_workspace, "Feign DTO 兼容改造")["session_id"])
    workspace_log_session_event(
        demo_workspace, sid, "tool_call", {"tool_name": "mc_analyze", "query": "MoveArticleRequest", "file_path": "common-api/src/main/java/Feign.java"}
    )
    workspace_log_session_event(demo_workspace, sid, "tool_call", {"tool_name": "mc_lookup", "query": "q", "project": "common-api"})
    workspace_end_session(demo_workspace, sid, outcome="完成", verified_by=["bob"])
    result = workspace_consolidate_sessions(demo_workspace, [sid], stage=True)
    candidate = result["candidates"][0]
    assert candidate["operation"] == "ADD", candidate["reason"]

    decision = workspace_decide_consolidation_candidate(demo_workspace, candidate["candidate_id"], decision="approve", actor="m1")
    assert decision.get("applied") is True, decision
    notes = decision.get("merge_notes") or []
    assert notes, "merge notes should explain what was merged"

    rows = WorkspaceStore(demo_workspace).read_jsonl_prefer_backend("cross-service-task-memory.jsonl", limit=20)
    newest = rows[-1]
    assert newest["task"] == "Feign DTO 兼容改造"
    assert newest["executions"] == 8, "sum op must carry every superseded case count"
    assert newest["successes"] == 6
    assert "alice" in newest["verified_by"], "append op must carry verified_by from superseded case"
    assert "carol" in newest["verified_by"]
    assert newest["current_truth"] is True


def test_approve_without_superseded_cases_has_no_merge_notes(demo_workspace: Path) -> None:
    workspace = str(demo_workspace)
    workspace_record_case(workspace, task="别的主题任务", projects=["other"], files=[], current_truth=False)
    candidate_id, _sid = _stage_candidate(demo_workspace, "全新主题:MQ 幂等改造")
    decision = workspace_decide_consolidation_candidate(demo_workspace, candidate_id, decision="approve", actor="m1")
    assert decision.get("applied") is True
    assert not (decision.get("merge_notes") or [])
