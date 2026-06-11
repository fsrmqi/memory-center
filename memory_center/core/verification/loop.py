"""Verification Loop — analyze -> checklist -> verify -> close.

Implements ECC-2 from NEXT_PHASE_MASTER_PLAN.md.
Provides a structured verification workflow for coding agents.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

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
        task_id = ""
        try:
            entries = self._store.read_jsonl(VERIFICATION_LOG_FILE)
        except Exception:
            entries = []
        for existing in entries:
            if existing.get("loop_id") == loop_id and existing.get("task_id"):
                task_id = str(existing.get("task_id") or "")
                break
        entry = {
            "loop_id": loop_id,
            "task_id": task_id,
            "phase": phase,
            "status": "completed",
            "data": data,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        self._store.append_jsonl(VERIFICATION_LOG_FILE, entry)
        feedback = self._record_phase_feedback(task_id=task_id, phase=phase, data=data)
        if feedback:
            entry["feedback"] = feedback
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

    def check_completion(self, task_id: str) -> Dict[str, Any]:
        """Check if all verification items are completed for a task.

        Returns completion status with pending items and recommendations.
        Never raises.
        """
        try:
            entries = self._store.read_jsonl(VERIFICATION_LOG_FILE)
        except Exception:
            entries = []

        task_entries = [e for e in entries if e.get("task_id") == task_id]
        if not task_entries:
            return {
                "task_id": task_id,
                "status": "no_loop",
                "completion_pct": 0,
                "pending_phases": ["analyze", "checklist", "verify", "close"],
                "message": "No verification loop found for this task",
            }

        # Find the start entry (which has the phases dict) and collect
        # completed phase names from complete_phase entries.
        # complete_phase entries use loop_id (not task_id), so we also
        # search by loop_id once we find the start entry.
        start_entry = None
        loop_id = ""
        for entry in task_entries:
            if "phases" in entry:
                start_entry = entry
                loop_id = entry.get("loop_id", "")

        # Collect all entries for this loop (including complete_phase entries)
        if loop_id:
            loop_entries = [e for e in entries if e.get("loop_id") == loop_id]
        else:
            loop_entries = task_entries

        completed_phase_names: set = set()
        for entry in loop_entries:
            if entry.get("phase") and entry.get("status") == "completed":
                completed_phase_names.add(entry["phase"])

        if start_entry:
            phases = dict(start_entry.get("phases", {}))
            # Update phase statuses from completed_phase entries
            for phase_name in completed_phase_names:
                if phase_name in phases:
                    phases[phase_name] = {"status": "completed"}
        else:
            # Build phases from completed entries if no start entry found
            phases = {}
            for name in ("analyze", "checklist", "verify", "close"):
                phases[name] = {"status": "completed" if name in completed_phase_names else "pending"}

        completed_phases = [p for p, v in phases.items() if v.get("status") == "completed"]
        pending_phases = [p for p, v in phases.items() if v.get("status") != "completed"]
        total = len(phases) if phases else 4
        completion_pct = round(len(completed_phases) / max(total, 1) * 100, 1)
        status = "completed" if not pending_phases and phases else (start_entry or task_entries[-1]).get("status", "unknown")

        return {
            "task_id": task_id,
            "loop_id": loop_id,
            "status": status,
            "completion_pct": completion_pct,
            "completed_phases": completed_phases,
            "pending_phases": pending_phases,
            "total_phases": total,
            "message": f"{len(completed_phases)}/{total} phases completed" if phases else "No phase data",
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
            return self.check_completion(task_id)
        return {"task_id": task_id, "status": "pending", "loop_id": ""}

    def _record_phase_feedback(self, task_id: str, phase: str, data: Dict[str, Any]) -> Dict[str, Any] | None:
        if phase != "verify" or not isinstance(data, dict):
            return None
        candidate_type = str(data.get("candidate_type", "") or "")
        target = str(data.get("target", "") or "")
        outcome = str(data.get("outcome", "") or "")
        if not candidate_type or not target or not outcome:
            return None

        from .heuristics import HeuristicsRegister

        register = HeuristicsRegister(self._store.workspace_file)
        feedback = register.record_candidate_path_feedback(
            candidate_type=candidate_type,
            target=target,
            outcome=outcome,
            evidence=data.get("evidence") or [],
            source=str(data.get("source", "") or "verification_loop"),
            task_id=task_id,
            session_id=str(data.get("session_id", "") or ""),
            weight_before=data.get("weight_before"),
            weight_delta=data.get("weight_delta"),
            why=str(data.get("why", "") or "verification loop verify phase completed"),
            next_action=str(data.get("next_action", "") or ""),
            verification_cost=str(data.get("verification_cost", "") or "medium"),
            category=str(data.get("category", "") or "candidate-path"),
            pattern=str(data.get("pattern", "") or ""),
            trigger=str(data.get("trigger", "") or ""),
        )
        return {"recorded": True, "item": feedback}

    def persist_step_state(
        self,
        loop_id: str,
        phase: str,
        step_name: str,
        state: str,
        output_refs: List[Dict[str, Any]] | None = None,
        diagnostics: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Persist step-level state for resumable workflow (H-04).

        Each step records: phase, step_name, state (created|running|paused|failed|completed|aborted),
        input summary, output refs, diagnostics, and timestamps.
        Supports resume from failed/paused steps without re-executing completed ones.
        """
        entry = {
            "loop_id": loop_id,
            "phase": phase,
            "step_name": step_name,
            "state": state,
            "output_refs": output_refs or [],
            "diagnostics": diagnostics or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._store.append_jsonl(VERIFICATION_LOG_FILE, entry)
        return entry

    def get_step_states(self, loop_id: str) -> List[Dict[str, Any]]:
        """Get all step states for a loop, enabling resume from last completed step."""
        try:
            entries = self._store.read_jsonl(VERIFICATION_LOG_FILE)
        except Exception:
            entries = []
        return [e for e in entries if e.get("loop_id") == loop_id and "step_name" in e]

    def resume_from_last_step(self, loop_id: str) -> Dict[str, Any]:
        """Determine which step to resume from based on persisted state."""
        steps = self.get_step_states(loop_id)
        if not steps:
            return {"loop_id": loop_id, "resume_from": "beginning", "completed_steps": []}

        completed = [s for s in steps if s.get("state") == "completed"]
        failed = [s for s in steps if s.get("state") == "failed"]
        paused = [s for s in steps if s.get("state") == "paused"]

        if paused:
            last = paused[-1]
            return {
                "loop_id": loop_id,
                "resume_from": last.get("step_name", ""),
                "resume_phase": last.get("phase", ""),
                "completed_steps": [s.get("step_name") for s in completed],
                "reason": "paused",
            }
        if failed:
            last = failed[-1]
            return {
                "loop_id": loop_id,
                "resume_from": last.get("step_name", ""),
                "resume_phase": last.get("phase", ""),
                "completed_steps": [s.get("step_name") for s in completed],
                "reason": "failed",
            }
        # All steps completed
        return {
            "loop_id": loop_id,
            "resume_from": "none",
            "completed_steps": [s.get("step_name") for s in completed],
            "reason": "all_completed",
        }
