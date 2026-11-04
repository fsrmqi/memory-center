from __future__ import annotations

from pathlib import Path

import yaml

from memory_center.core.benchmark.session_recall import evaluate_session_recall
from memory_center.core.orchestrator.resume import workspace_resume_context
from memory_center.core.orchestrator.write import workspace_record_case


def _write_cases(path: Path, cases: list[dict]) -> Path:
    target = path / "private-session-recall-cases.yaml"
    target.write_text(yaml.safe_dump({"schema_version": 1, "cases": cases}, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return target


def test_session_recall_classifies_hit_index_retrieval_and_window_misses(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    workspace_record_case(str(workspace), "订单数据自动隔离", ["task-service"], ["OrderIsolation.java"], source_session_id="session-hit")
    workspace_record_case(str(workspace), "任务隔离策略一", ["task-service"], ["TaskPolicy.java"], source_session_id="session-window-target")
    workspace_record_case(str(workspace), "任务隔离策略二", ["task-service"], ["TaskPolicyV2.java"], source_session_id="session-window-newer")
    workspace_record_case(str(workspace), "消息重试处理", ["task-service"], ["Retry.java"], source_session_id="session-retrieval-target")
    cases = _write_cases(
        tmp_path,
        [
            {"id": "hit", "query": "订单数据自动隔离", "expected_source_session_id": "session-hit"},
            {"id": "not-indexed", "query": "不存在的记忆", "expected_source_session_id": "session-missing"},
            {"id": "retrieval", "query": "支付超时", "expected_source_session_id": "session-retrieval-target"},
            {"id": "window", "query": "任务隔离", "expected_source_session_id": "session-window-target"},
        ],
    )

    result = evaluate_session_recall(str(workspace), cases, limit=1, resume_runner=workspace_resume_context)

    assert result["status"] == "ready"
    assert result["classifications"] == {
        "hit": 1,
        "case_not_indexed": 1,
        "retrieval_miss": 1,
        "ranking_miss": 1,
        "evidence_insufficient": 0,
    }
    assert result["recall"] == 0.25
    assert result["related_case_match_modes"]["exact"] >= 1
    assert all("订单" not in str(row) and "session-hit" not in str(row) for row in result["cases"])


def test_session_recall_marks_missing_expectation_as_insufficient(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    cases = _write_cases(tmp_path, [{"id": "incomplete", "query": "订单隔离"}])

    result = evaluate_session_recall(str(workspace), cases, resume_runner=workspace_resume_context)

    assert result["status"] == "insufficient_cases"
    assert result["classifications"]["evidence_insufficient"] == 1
    assert result["recall"] is None


def test_session_recall_reports_review_candidates_only_for_labeled_precision(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    workspace_record_case(str(workspace), "任务隔离策略一", ["task-service"], ["One.java"], source_session_id="session-allowed")
    workspace_record_case(str(workspace), "任务隔离策略二", ["task-service"], ["Two.java"], source_session_id="session-review")
    cases = _write_cases(
        tmp_path,
        [{"id": "precision", "query": "任务隔离", "expected_source_session_id": "session-allowed", "allowed_source_session_ids": ["session-allowed"]}],
    )

    result = evaluate_session_recall(str(workspace), cases, limit=5, resume_runner=workspace_resume_context)

    assert result["precision_review"] == {
        "labeled_case_count": 1,
        "returned_count": 2,
        "allowed_returned_count": 1,
        "unexpected_return_count": 1,
        "precision": 0.5,
        "note": "unexpected means human review required, not an automatic false-positive judgment",
    }
    assert result["cases"][0]["unexpected_source_session_sha256"]
    assert "审核 unexpected" in result["next_action"]
