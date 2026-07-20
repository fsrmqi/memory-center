from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

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


def test_recent_change_reports_are_available_from_cli(tmp_path: Path) -> None:
    from memory_center.cli.main import app
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    record_change_impact_report(workspace, changed_paths=["api/src/main/java/example/A.java"], trigger_result={}, job=_completed_job())

    result = CliRunner().invoke(app, ["change-impact-reports", "--workspace", str(workspace)])

    assert result.exit_code == 0
    assert '"count": 1' in result.output
    assert recent_change_impact_reports(workspace)["reports"][0]["job"]["job_id"] == "job-1"


def test_change_reports_share_http_and_mcp_read_model(tmp_path: Path) -> None:
    from memory_center.application.admin import build_admin_registry
    from memory_center.http.route_dispatch import build_http_route_registry
    from memory_center.http.routes.params import RouteParams
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    report = record_change_impact_report(workspace, changed_paths=["api/src/main/java/example/A.java"], trigger_result={}, job=_completed_job())

    mcp = build_admin_registry(workspace_file=str(workspace), limit=5).dispatch("change_impact_recent")
    http = build_http_route_registry().dispatch(
        "/workspace/change-impact-reports",
        RouteParams({"workspace": [str(workspace)]}, str(workspace)),
    )

    assert mcp["reports"][0]["report_id"] == report["report_id"]
    assert http["reports"][0]["report_id"] == report["report_id"]


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

    assert result["recorded"] is True
    feedback = result["feedback"]
    assert feedback["status"] == "closed"
    assert feedback["evidence_level"] == "VERIFIED"
    assert feedback["validation_summary"] == "pytest passed all checks complete"
    assert feedback["verified_by"] == ["qa"]
    report_view = recent_change_impact_reports(workspace)["reports"][0]
    assert report_view["feedback"]["task_id"] == "task-123"
    assert pending_change_impact_reports(workspace)["high_risk_reports"] == []


def test_change_report_deep_analysis_request_stays_pending_and_all_entrypoints_confirm(tmp_path: Path) -> None:
    from memory_center.application.admin import build_admin_registry
    from memory_center.cli.main import app
    from memory_center.http.route_dispatch import build_http_route_registry
    from memory_center.http.routes.params import RouteParams
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    report = record_change_impact_report(workspace, changed_paths=["api/src/main/java/example/A.java"], trigger_result={}, job=_completed_job())
    mcp = build_admin_registry(
        workspace_file=str(workspace),
        record_id=report["report_id"],
        action_filter="deep_analysis_required",
        payload='{"validation_status":"recorded","note":"need full trace"}',
    ).dispatch("change_impact_confirm")
    assert mcp["feedback"]["status"] == "pending"
    assert pending_change_impact_reports(workspace)["reports"][0]["report_id"] == report["report_id"]

    http = build_http_route_registry().dispatch(
        "/workspace/change-impact-confirm",
        RouteParams(
            {
                "workspace": [str(workspace)],
                "report_id": [report["report_id"]],
                "decision": ["resolved"],
                "validation_status": ["passed"],
                "verified_by": ["owner"],
            },
            str(workspace),
        ),
    )
    assert http["feedback"]["decision"] == "resolved"

    second = record_change_impact_report(workspace, changed_paths=["api/src/main/java/example/B.java"], trigger_result={}, job=_completed_job())
    cli = CliRunner().invoke(
        app,
        [
            "change-impact-confirm",
            "--workspace",
            str(workspace),
            "--report-id",
            second["report_id"],
            "--decision",
            "false_positive",
        ],
    )
    assert cli.exit_code == 0
    assert '"recorded": true' in cli.output
