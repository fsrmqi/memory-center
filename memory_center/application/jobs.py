"""后台任务与任务证据的应用层操作。"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from memory_center.core.tasks.artifacts import write_task_evidence_chunk
from memory_center.core.workspace.jobs import cancel_workspace_job, submit_workspace_job, workspace_job_status


def analysis_job_status(workspace_file: str, job_id: str = "", *, limit: int = 20) -> dict[str, Any]:
    return workspace_job_status(workspace_file, job_id, limit=limit)


def cancel_analysis_job(workspace_file: str, job_id: str) -> dict[str, Any]:
    return cancel_workspace_job(workspace_file, job_id)


def submit_analysis_job(workspace_file: str, operation: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    return submit_workspace_job(workspace_file, "analysis", operation)


def write_contract_evidence(workspace_file: str, task_id: str, contract: dict[str, Any]) -> dict[str, Any]:
    try:
        return write_task_evidence_chunk(
            workspace_file,
            task_id,
            json.dumps(contract, ensure_ascii=False, indent=2),
            source="mc_analyze_contract",
        )
    except Exception as exc:
        return {"stored": False, "reason": str(exc)}
