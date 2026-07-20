from __future__ import annotations

import time
from pathlib import Path

from typer.testing import CliRunner

from memory_center.core.workspace.jobs import PROGRESS_STAGES, submit_workspace_job, workspace_job_status


def test_background_job_persists_completed_result(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    job = submit_workspace_job(str(workspace), "test", lambda: {"ok": True})
    for _ in range(40):
        status = workspace_job_status(str(workspace), job["job_id"])
        if status.get("status") == "completed":
            break
        time.sleep(0.02)
    assert status["status"] == "completed"
    assert status["result"] == {"ok": True}


def test_background_job_persists_structured_progress_events(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)

    def progress_work(report):
        report("parsing", 30, "parsing fixture")
        report("graph", 55, "building graph")
        report("semantic", 70, "building semantic index")
        return {"ok": True}

    job = submit_workspace_job(str(workspace), "test", lambda: {"unexpected": True}, progress_work=progress_work)
    for _ in range(40):
        status = workspace_job_status(str(workspace), job["job_id"])
        if status.get("status") == "completed":
            break
        time.sleep(0.02)

    events = status["progress_events"]
    assert status["progress"]["stage"] == "completed"
    assert [event["percent"] for event in events] == sorted(event["percent"] for event in events)
    assert {event["stage"] for event in events}.issubset(PROGRESS_STAGES)
    assert {"queued", "scanning", "parsing", "graph", "semantic", "finalizing", "completed"}.issubset(
        {event["stage"] for event in events}
    )


def test_failed_job_keeps_last_real_progress(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)

    def progress_work(report):
        report("parsing", 30, "parsing fixture")
        raise RuntimeError("fixture failure")

    job = submit_workspace_job(str(workspace), "test", lambda: {}, progress_work=progress_work)
    for _ in range(40):
        status = workspace_job_status(str(workspace), job["job_id"])
        if status.get("status") == "failed":
            break
        time.sleep(0.02)

    assert status["status"] == "failed"
    assert status["progress"]["stage"] == "failed"
    assert status["progress"]["percent"] == 30


def test_job_status_is_available_from_cli_http_and_workspace_status(tmp_path: Path) -> None:
    from memory_center.cli.main import app
    from memory_center.core.orchestrator import workspace_status
    from memory_center.http.route_dispatch import build_http_route_registry
    from memory_center.http.routes.params import RouteParams
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    job = submit_workspace_job(str(workspace), "test", lambda: {"ok": True})
    for _ in range(40):
        status = workspace_job_status(str(workspace), job["job_id"])
        if status.get("status") == "completed":
            break
        time.sleep(0.02)

    cli = CliRunner().invoke(app, ["job-status", "--workspace", str(workspace), "--job-id", job["job_id"]])
    assert cli.exit_code == 0
    assert job["job_id"] in cli.output

    route = build_http_route_registry().dispatch(
        "/workspace/job-status",
        RouteParams({"workspace": [str(workspace)], "job_id": [job["job_id"]]}, str(workspace)),
    )
    assert route["job_id"] == job["job_id"]
    assert workspace_status(workspace, view="compact")["jobs"]["jobs"][0]["job_id"] == job["job_id"]


def test_reindex_reports_all_main_stages(tmp_path: Path) -> None:
    from memory_center.core.indexing.reindex import reindex_workspace
    from memory_center.core.storage.workspace import WorkspaceStore
    from memory_center.core.workspace.config import load_workspace_config
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    stages: list[str] = []
    reindex_workspace(
        load_workspace_config(workspace),
        WorkspaceStore(workspace),
        parallel=False,
        progress=lambda stage, _percent, _message: stages.append(stage),
    )

    assert {"scanning", "parsing", "graph", "semantic", "retrieval", "finalizing"}.issubset(stages)
