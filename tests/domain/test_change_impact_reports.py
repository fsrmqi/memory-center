from __future__ import annotations

from pathlib import Path

import pytest

from memory_center.core.freshness.change_reports import (
    pending_change_impact_reports,
    recent_change_impact_reports,
    record_change_impact_feedback,
    record_change_impact_report,
)


def _completed_job() -> dict:
    return {
        "job_id": "job-1",
        "status": "completed",
        "progress": {"stage": "completed", "percent": 100},
        "result": {"mode": "partial", "files": 2, "symbols": 3},
    }


def test_change_report_is_bounded_and_marks_contract_risk(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    report = record_change_impact_report(
        workspace,
        changed_paths=["api/src/main/java/example/OrderDto.java"],
        trigger_result={
            "dirty_journal": {
                "invalidation": {
                    "categories": ["dto_contract"],
                    "impacted_paths": ["api/src/main/java/example/OrderDto.java", "service/src/main/java/example/OrderClient.java"],
                }
            }
        },
        job=_completed_job(),
    )

    assert report["risk_level"] == "high"
    assert report["evidence_level"] == "EXTRACTED"
    assert report["dependency_evidence_level"] == "INFERRED"
    assert "mc_analyze" in report["next_action"]
    assert report["job"]["counts"] == {"mode": "partial", "files": 2, "symbols": 3}


def test_failed_change_report_does_not_claim_ready(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    report = record_change_impact_report(
        workspace,
        changed_paths=["api/src/main/java/example/OrderController.java"],
        trigger_result={},
        job={"job_id": "job-2", "status": "failed", "error": "safe failure", "progress": {"percent": 50}},
    )

    assert report["status"] == "reindex_failed"
    assert "失败原因" in report["next_action"]


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_recent_change_reports_are_available_from_cli(tmp_path: Path) -> None:
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_change_reports_share_http_and_mcp_read_model(tmp_path: Path) -> None:
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


def test_change_report_confirmation_closes_high_risk_report_with_validation_context(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    report = record_change_impact_report(
        workspace,
        changed_paths=["api/src/main/java/example/OrderDto.java"],
        trigger_result={"dirty_journal": {"invalidation": {"categories": ["dto_contract"]}}},
        job=_completed_job(),
    )

    result = record_change_impact_feedback(
        workspace,
        report["report_id"],
        decision="confirmed",
        task_id="task-123",
        session_id="session-456",
        validation_status="passed",
        validation_summary="pytest passed\nall checks complete",
        verified_by=["qa", "qa"],
        note="contract compatibility confirmed",
    )
    assert result["governance"]["projected"] == 2

    assert result["recorded"] is True
    feedback = result["feedback"]
    assert feedback["status"] == "closed"
    assert feedback["evidence_level"] == "VERIFIED"
    assert feedback["validation_summary"] == "pytest passed all checks complete"
    assert feedback["verified_by"] == ["qa"]
    report_view = recent_change_impact_reports(workspace)["reports"][0]
    assert report_view["feedback"]["task_id"] == "task-123"
    assert pending_change_impact_reports(workspace)["high_risk_reports"] == []


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_change_report_deep_analysis_request_stays_pending_and_all_entrypoints_confirm(tmp_path: Path) -> None:
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")
