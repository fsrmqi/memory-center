"""任务恢复前的健康门禁与下一步建议。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..tasks.artifacts import task_space_repair_plan
from .resume import workspace_next_actions, workspace_resume_packet, workspace_unresolved_items
from .session import workspace_recent_evidence


def workspace_task_resume_check(
    workspace_file: str | Path,
    intent: str = "",
    task_id: str = "",
    session_id: str = "",
    limit: int = 8,
    budget: str = "medium",
) -> dict[str, Any]:
    """组合恢复包、健康报告和只读修复建议，给出可接手结论。"""
    resume_packet = workspace_resume_packet(
        workspace_file,
        task_id=task_id,
        session_id=session_id,
        intent=intent,
        limit=limit,
        view="compact",
        budget=budget,
    )
    resolved_task_id = str(resume_packet.get("task_id", "") or task_id or "")
    health = resume_packet.get("task_health", {}) or {}
    repair_hint = resume_packet.get("repair_plan_hint", {}) or {}
    repair_plan = task_space_repair_plan(workspace_file, resolved_task_id) if bool(repair_hint.get("available")) and resolved_task_id else {
        "repair_plan": [], "issue_count": 0, "apply_supported": False,
    }
    next_actions = workspace_next_actions(workspace_file, task_id=resolved_task_id, session_id=session_id, intent=intent, limit=limit).get("actions", [])
    unresolved = workspace_unresolved_items(workspace_file, task_id=resolved_task_id, session_id=session_id, intent=intent, limit=limit).get("items", [])
    evidence = workspace_recent_evidence(workspace_file, task_id=resolved_task_id, session_id=session_id, limit=min(limit, 5), budget=budget, view="compact").get("evidence", [])
    status = _resume_check_status(resume_packet, health, repair_plan, unresolved)
    return {
        "workflow": "task-resume-check", "workspace": resume_packet.get("workspace", ""), "task_id": resolved_task_id,
        "session_id": session_id, "can_resume": status in {"ready", "needs_repair"}, "status": status,
        "summary": _resume_check_summary(status, health, repair_plan, unresolved), "resume_packet": resume_packet,
        "health": health, "repair_plan": repair_plan.get("repair_plan", []),
        "repair_plan_summary": {"available": bool(repair_hint.get("available")), "issue_count": repair_plan.get("issue_count", health.get("issue_count", 0)), "apply_supported": repair_plan.get("apply_supported", False)},
        "next_actions": next_actions, "unresolved_items": unresolved, "recent_evidence": evidence,
        "recommended_next_step": _resume_check_next_step(status, resolved_task_id),
    }


def _resume_check_status(resume_packet: dict[str, Any], health: dict[str, Any], repair_plan: dict[str, Any], unresolved: list[dict[str, Any]]) -> str:
    if not resume_packet.get("task_id"):
        return "blocked"
    if str(health.get("health", "")) == "bad" or repair_plan.get("repair_plan"):
        return "needs_repair"
    if resume_packet.get("verification_pending") or unresolved:
        return "blocked"
    if str(resume_packet.get("resume_readiness", "")) == "partial" or str(health.get("health", "")) == "warning":
        return "needs_repair"
    return "blocked" if str(resume_packet.get("resume_readiness", "")) == "blocked" else "ready"


def _resume_check_summary(status: str, health: dict[str, Any], repair_plan: dict[str, Any], unresolved: list[dict[str, Any]]) -> str:
    issue_count = int(health.get("issue_count", 0) or repair_plan.get("issue_count", 0) or 0)
    repair_count = len(repair_plan.get("repair_plan", []) if isinstance(repair_plan.get("repair_plan", []), list) else [])
    if status == "ready":
        return "任务空间健康，恢复包可直接接手。"
    if status == "blocked":
        return f"任务存在 {len(unresolved)} 个未解决项，接手前需要先处理阻塞。" if unresolved else "恢复包缺少关键上下文或处于阻塞状态，接手前需要补齐。"
    return f"任务可接手但建议先处理 {issue_count} 个健康问题，已生成 {repair_count} 条只读修复动作。" if repair_count else f"任务可接手但健康状态为 {health.get('health', 'unknown')}，建议先复核健康检查结果。"


def _resume_check_next_step(status: str, task_id: str) -> dict[str, Any]:
    if status == "ready":
        return {"action": "resume", "command": "继续按 resume_packet.next_recommended_actions 执行", "requires_write": False}
    if status == "needs_repair":
        command = f"mc_admin(action='task_repair_plan', task_id='{task_id}')" if task_id else "mc_admin(action='task_repair_plan', task_id='...')"
        return {"action": "repair_plan", "command": command, "requires_write": False}
    return {"action": "resolve_blocker", "command": "先处理 unresolved_items 或补齐 current_summary/write_receipts", "requires_write": False}
