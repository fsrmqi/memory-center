"""任务恢复前的健康门禁与下一步建议。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..tasks.artifacts import task_space_repair_plan
from ..tasks.delivery import delivery_matrix, delivery_task_metrics, delivery_workflow_status
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
    delivery = delivery_workflow_status(workspace_file, resolved_task_id) if resolved_task_id else {"initialized": False}
    matrix = delivery_matrix(workspace_file, resolved_task_id, write=False).get("matrix", {}) if delivery.get("initialized") else {}
    metrics = delivery_task_metrics(workspace_file, resolved_task_id) if delivery.get("initialized") else {}
    delivery_hints = _delivery_matrix_hints(matrix, metrics)
    status = _resume_check_status(resume_packet, health, repair_plan, unresolved)
    return {
        "workflow": "task-resume-check", "workspace": resume_packet.get("workspace", ""), "task_id": resolved_task_id,
        "session_id": session_id, "can_resume": status in {"ready", "needs_repair"}, "status": status,
        "summary": _resume_check_summary(status, health, repair_plan, unresolved), "resume_packet": resume_packet,
        "health": health, "repair_plan": repair_plan.get("repair_plan", []),
        "delivery": delivery, "delivery_matrix": matrix, "delivery_metrics": metrics,
        "delivery_hints": delivery_hints,
        "repair_plan_summary": {"available": bool(repair_hint.get("available")), "issue_count": repair_plan.get("issue_count", health.get("issue_count", 0)), "apply_supported": repair_plan.get("apply_supported", False)},
        "next_actions": next_actions, "unresolved_items": unresolved, "recent_evidence": evidence,
        "recommended_next_step": _resume_check_next_step(status, resolved_task_id, delivery_hints),
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


def _resume_check_next_step(status: str, task_id: str, delivery_hints: dict[str, Any] | None = None) -> dict[str, Any]:
    if status == "ready":
        return {"action": "resume", "command": "继续按 resume_packet.next_recommended_actions 执行", "requires_write": False}
    if status == "needs_repair":
        command = f"mc_admin(action='task_repair_plan', task_id='{task_id}')" if task_id else "mc_admin(action='task_repair_plan', task_id='...')"
        return {"action": "repair_plan", "command": command, "requires_write": False}
    hints = delivery_hints or {}
    if hints.get("unresolved_ambiguities"):
        return {
            "action": "resolve_ambiguity",
            "command": "先处理未决歧义：确认需求范围或验收标准",
            "details": hints["unresolved_ambiguities"][:5],
            "requires_write": False,
        }
    if hints.get("failed_validations"):
        return {
            "action": "fix_failed_validation",
            "command": "先修复失败的验证项",
            "details": hints["failed_validations"][:5],
            "requires_write": True,
        }
    return {"action": "resolve_blocker", "command": "先处理 unresolved_items 或补齐 current_summary/write_receipts", "requires_write": False}


def _delivery_matrix_hints(matrix: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    """Extract actionable hints from delivery matrix and metrics."""
    rows = matrix.get("rows", [])
    ambiguities = []
    failed_validations = []
    for row in rows:
        if row.get("ambiguities"):
            ambiguities.append({"requirement_id": row.get("requirement_id"), "title": row.get("title"), "ambiguities": row["ambiguities"]})
        for acceptance in row.get("acceptance", []):
            if not acceptance.get("verified"):
                failed_validations.append({"acceptance_id": acceptance.get("id"), "title": acceptance.get("title")})
    coverage = metrics.get("coverage", {})
    verification = metrics.get("verification", {})
    failure_classification = metrics.get("failure_classification", {})
    return {
        "unresolved_ambiguities": ambiguities,
        "failed_validations": failed_validations,
        "requirement_coverage": coverage.get("requirement_coverage", 0),
        "acceptance_coverage": coverage.get("acceptance_coverage", 0),
        "verification_success_rate": verification.get("success_rate", 0),
        "failure_categories": failure_classification,
        "has_critical_gaps": bool(ambiguities or failed_validations),
    }
