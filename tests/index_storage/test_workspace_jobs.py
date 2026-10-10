from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

from memory_center.core.workspace.jobs import (
    JOBS_FILE,
    PROGRESS_STAGES,
    cancel_workspace_job,
    submit_workspace_job,
    workspace_job_status,
)


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
    assert status["progress_percent"] == 100
    assert status["can_cancel"] is False
    assert status["recovery_action"]["action"] == "none"


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


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_job_status_is_available_from_cli_http_and_workspace_status(tmp_path: Path) -> None:
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


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


def test_current_process_long_running_job_is_not_marked_interrupted(tmp_path: Path) -> None:
    from memory_center.core.storage.workspace import WorkspaceStore
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    store = WorkspaceStore(workspace)
    store.write_json(
        JOBS_FILE,
        [
            {
                "job_id": "job-long",
                "kind": "reindex",
                "status": "running",
                "runner_pid": os.getpid(),
                "updated_at": time.time() - 3600,
                "progress": {"stage": "parsing", "percent": 30},
            }
        ],
    )

    status = workspace_job_status(str(workspace), "job-long")

    assert status["status"] == "running"
    assert status["can_cancel"] is True
    assert status["progress_percent"] == 30
    assert status["estimated_remaining_ms"] is not None


def test_cancellation_is_persisted_and_observed_at_progress_boundary(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    started = threading.Event()
    release = threading.Event()

    def progress_work(report):
        report("parsing", 30, "started")
        started.set()
        release.wait(1)
        report("graph", 55, "should cancel")
        return {"unexpected": True}

    job = submit_workspace_job(str(workspace), "test", lambda: {}, progress_work=progress_work)
    assert started.wait(1)
    assert cancel_workspace_job(str(workspace), job["job_id"])["status"] == "cancel_requested"
    release.set()
    for _ in range(40):
        status = workspace_job_status(str(workspace), job["job_id"])
        if status.get("status") == "cancelled":
            break
        time.sleep(0.02)
    assert status["status"] == "cancelled"
