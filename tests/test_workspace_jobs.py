from __future__ import annotations

import time
from pathlib import Path

from memory_center.core.workspace.jobs import submit_workspace_job, workspace_job_status


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
