from __future__ import annotations

import time
from pathlib import Path

from typer.testing import CliRunner

from memory_center.core.freshness.change_reports import recent_change_impact_reports
from memory_center.core.freshness.daemon import (
    WATCHER_DAEMON_FILE,
    record_watcher_batch,
    start_watcher_daemon,
    stop_watcher_daemon,
    watcher_daemon_status,
)
from memory_center.core.freshness.watcher import WatchEvent
from memory_center.core.storage.workspace import WorkspaceStore


def test_watcher_daemon_status_defaults_to_stopped(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    assert watcher_daemon_status(workspace) == {"status": "stopped", "active": False, "configured": False}


def test_start_watcher_daemon_uses_detached_cli_process(tmp_path: Path, monkeypatch) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    observed: dict[str, object] = {}

    class Process:
        pid = 32123

    def fake_popen(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        return Process()

    monkeypatch.setattr("memory_center.core.freshness.daemon.subprocess.Popen", fake_popen)
    result = start_watcher_daemon(workspace, poll_interval=0.5, debounce_seconds=0.1)

    assert result["started"] is True
    assert result["pid"] == 32123
    assert "watcher-run" in observed["command"]
    assert observed["kwargs"]["start_new_session"] is True


def test_watcher_batch_records_changes_and_job(tmp_path: Path, monkeypatch) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    monkeypatch.setattr(
        "memory_center.core.freshness.daemon.trigger_incremental_reindex",
        lambda _workspace, paths: {"status": "queued", "changed_files": len(paths), "reindex_job": {"job_id": "job-1"}},
    )
    result = record_watcher_batch(workspace, [WatchEvent("api/src/A.java", "modified"), WatchEvent("api/src/A.java", "modified")])
    state = WorkspaceStore(workspace).read_json(WATCHER_DAEMON_FILE, {})

    assert result["status"] == "queued"
    assert state["event_batches"] == 1
    assert state["changed_files"] == 1
    assert state["last_reindex_job"] == "job-1"


def test_watcher_batch_generates_report_after_completed_job(tmp_path: Path, monkeypatch) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    monkeypatch.setattr(
        "memory_center.core.freshness.daemon.trigger_incremental_reindex",
        lambda _workspace, paths: {
            "status": "queued",
            "changed_files": len(paths),
            "dirty_journal": {"invalidation": {"categories": ["dto_contract"], "impacted_paths": paths}},
            "reindex_job": {"job_id": "job-completed"},
        },
    )
    monkeypatch.setattr(
        "memory_center.core.workspace.jobs.workspace_job_status",
        lambda _workspace, _job_id: {"job_id": "job-completed", "status": "completed", "result": {"files": 1}},
    )

    record_watcher_batch(workspace, [WatchEvent("api/src/main/java/example/OrderDto.java", "modified")])
    for _ in range(20):
        reports = recent_change_impact_reports(workspace)["reports"]
        if reports:
            break
        time.sleep(0.02)

    assert reports[0]["job"]["status"] == "completed"
    assert reports[0]["risk_level"] == "high"


def test_stop_watcher_daemon_requests_sigterm(tmp_path: Path, monkeypatch) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    WorkspaceStore(workspace).write_json(WATCHER_DAEMON_FILE, {"status": "running", "pid": 32123})
    monkeypatch.setattr("memory_center.core.freshness.daemon._pid_alive", lambda _pid: True)
    observed: dict[str, int] = {}
    monkeypatch.setattr("memory_center.core.freshness.daemon.os.kill", lambda pid, sig: observed.update(pid=pid, sig=sig))

    result = stop_watcher_daemon(workspace)

    assert result["stopped"] is True
    assert observed["pid"] == 32123


def test_watcher_cli_status_is_available(tmp_path: Path) -> None:
    from memory_center.cli.main import app
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    result = CliRunner().invoke(app, ["watcher-status", "--workspace", str(workspace)])

    assert result.exit_code == 0
    assert '"status": "stopped"' in result.output
