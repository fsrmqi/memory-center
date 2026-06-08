"""Verification Loop — analyze -> checklist -> verify -> close.

Implements ECC-2 from NEXT_PHASE_MASTER_PLAN.md.
Provides a structured verification workflow for coding agents.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..store import WorkspaceStore

VERIFICATION_LOG_FILE = "verification-loops.jsonl"


class VerificationLoop:
    """Structured verification workflow for agent tasks."""

    def __init__(self, workspace_file: str | Path):
        self._store = WorkspaceStore(workspace_file)

    def start(self, task_id: str, description: str) -> Dict[str, Any]:
        """Start a new verification loop."""
        loop = {
            "loop_id": f"verify-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            "task_id": task_id,
            "description": description,
            "status": "started",
            "phases": {
                "analyze": {"status": "pending", "findings": []},
                "checklist": {"status": "pending", "items": []},
                "verify": {"status": "pending", "results": []},
                "close": {"status": "pending", "summary": ""},
            },
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        self._store.append_jsonl(VERIFICATION_LOG_FILE, loop)
        return loop

    def complete_phase(self, loop_id: str, phase: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Complete a phase of the verification loop."""
        entry = {
            "loop_id": loop_id,
            "phase": phase,
            "status": "completed",
            "data": data,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        self._store.append_jsonl(VERIFICATION_LOG_FILE, entry)
        return entry

    def get_checklist(self, task_type: str = "general") -> List[str]:
        """Get verification checklist for a task type."""
        checklists = {
            "code_change": [
                "代码变更是否与需求描述一致",
                "是否添加了必要的单元测试",
                "测试是否全部通过",
                "是否更新了相关文档",
                "是否有未处理的异常或边界情况",
            ],
            "feature": [
                "功能是否按规格实现",
                "是否有完整的测试覆盖",
                "是否向后兼容",
                "性能是否满足要求",
                "安全审计是否通过",
            ],
            "bugfix": [
                "是否修复了根本原因",
                "是否添加了回归测试",
                "是否影响了其他功能",
                "修复是否最小化变更",
            ],
            "general": [
                "变更是否符合项目规范",
                "测试是否通过",
                "文档是否更新",
            ],
        }
        return checklists.get(task_type, checklists["general"])

    def generate_close_summary(self, task_id: str) -> Dict[str, Any]:
        """Generate a close summary for a completed verification loop."""
        return {
            "task_id": task_id,
            "summary": f"Verification loop completed for task {task_id}",
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }

    def generate_checklist(self, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a verification checklist from task analysis.

        Called by CLI / HTTP / MCP entry points.
        Returns a dict with ``task_type`` and ``items`` keys.
        """
        task_type = (analysis or {}).get("task_type", "general")
        items = self.get_checklist(task_type)
        return {"task_type": task_type, "items": items}

    def get_status(self, task_id: str) -> Dict[str, Any]:
        """Return the latest status for *task_id* from the verification log.

        Called by CLI / HTTP / MCP entry points.
        If no log entries exist for *task_id*, returns a default "pending" status.
        """
        try:
            entries = self._store.read_jsonl(VERIFICATION_LOG_FILE)
        except Exception:
            entries = []
        task_entries = [e for e in entries if e.get("task_id") == task_id]
        if task_entries:
            latest = task_entries[-1]
            return {
                "task_id": task_id,
                "status": latest.get("status", "unknown"),
                "loop_id": latest.get("loop_id", ""),
            }
        return {"task_id": task_id, "status": "pending", "loop_id": ""}
