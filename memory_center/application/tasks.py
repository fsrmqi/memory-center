"""任务维护类应用用例。"""
from __future__ import annotations

from pathlib import Path

from memory_center.core.orchestrator import workspace_sync_sniff_to_artifacts
from memory_center.core.tasks.artifacts import task_space_repair_execute


def execute_task_repair(workspace_file: str | Path, task_id: str, *, apply: bool = False, intent: str = "") -> dict[str, object]:
    def sync(workspace: str | Path, request_intent: str, target_task_id: str) -> dict[str, object]:
        return workspace_sync_sniff_to_artifacts(workspace, request_intent, task_id=target_task_id, limit=8)

    return task_space_repair_execute(workspace_file, task_id, apply=apply, intent=intent, sync_sniff=sync)
