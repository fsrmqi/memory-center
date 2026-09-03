"""mc_sync / mc_close 的 Task Shadow 逻辑（从 MCP server facade 下沉）。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from memory_center.core.orchestrator.session import (
    workspace_record_close_feedback,
    workspace_session_summary,
    workspace_suggest_case,
)
from memory_center.core.orchestrator.sync import _shadow_binding_for_session, workspace_sync_case_to_artifacts
from memory_center.core.tasks.shadow import build_merged_shadow, ensure_shadow_for_session

SHADOW_ID_PREFIX = "shadow:memory-center:"


def shadow_id_for_session(session_id: str) -> str:
    return f"{SHADOW_ID_PREFIX}{session_id}"


def shadow_only_sync(workspace_file: str | Path, session_id: str, intent: str, reason: str) -> dict[str, Any]:
    """sync_target=shadow 或低置信解析时的 fallback：只更新 Shadow，不写 L2。"""
    shadow = ensure_shadow_for_session(workspace_file, session_id, intent=intent)
    merged = build_merged_shadow(workspace_file, str(shadow["shadow_id"])) or {}
    return {
        "workflow": "mc-sync",
        "mode": "shadow",
        "synced": False,
        "write_target": "task_shadow",
        "binding_status": merged.get("binding_status", "unbound"),
        "shadow_id": shadow["shadow_id"],
        "reason": reason,
        "result": {"synced": False, "shadow_updated": True, "shadow_id": shadow["shadow_id"]},
    }


def case_sync_with_shadow(
    workspace_file: str | Path,
    session_id: str,
    *,
    task_id: str = "",
    title: str = "",
    auto_sync_mode: str = "balanced",
) -> dict[str, Any]:
    """session 维度的 case sync，附 write_target/binding_status 标注。

    L2 写入门禁（P0）：session 所属 Shadow 未绑定时，不允许
    workspace_sync_case_to_artifacts 自行 resolve/create task space——
    只更新 Shadow 并返回 explicit_task_id 所需动作；显式 task_id 或
    已有 bound Shadow 才放行 L2。
    """
    resolved_task_id = (task_id or "").strip()
    resolved_source = "explicit" if resolved_task_id else ""
    if not resolved_task_id:
        shadow = build_merged_shadow(workspace_file, shadow_id_for_session(session_id))
        if shadow is not None and shadow.get("binding_status") == "bound":
            resolved_task_id = str(shadow.get("bound_task_id", "") or "")
            resolved_source = "shadow_binding"
    if not resolved_task_id:
        fallback = shadow_only_sync(
            workspace_file,
            session_id,
            "",
            "shadow_not_bound: provide explicit task_id or bind the shadow before writing L2",
        )
        fallback["mode"] = "case"
        return fallback
    result = workspace_sync_case_to_artifacts(
        workspace_file, session_id, task_id=resolved_task_id, title=title, auto_sync_mode=auto_sync_mode
    )
    return {
        "workflow": "mc-sync",
        "mode": "case",
        "result": result,
        "write_target": "task_space" if result.get("synced") else "none",
        "binding_status": "bound" if resolved_source == "shadow_binding" else _shadow_binding_for_session(workspace_file, session_id),
        "task_id_source": resolved_source,
    }


def sniff_sync_with_shadow_fallback(
    workspace_file: str | Path,
    intent: str,
    *,
    limit: int = 12,
    task_id: str = "",
    title: str = "",
    auto_sync_mode: str = "balanced",
    session_id: str = "",
) -> dict[str, Any]:
    """intent 维度的 sniff sync：低置信解析时更新 Shadow 而不放弃连续性。"""
    result: dict[str, Any] = {
        "workflow": "mc-sync",
        "mode": "sniff",
        "result": _sniff_sync(workspace_file, intent, limit=limit, task_id=task_id, title=title, auto_sync_mode=auto_sync_mode),
    }
    if result["result"].get("synced"):
        result["write_target"] = "task_space"
    else:
        result["shadow_fallback"] = shadow_only_sync(
            workspace_file,
            session_id or f"anon-{abs(hash(intent)) % 10**10}",
            intent,
            str(result["result"].get("reason", "task_resolution_not_auto_writable")),
        )
        result["write_target"] = "task_shadow"
    result["binding_status"] = (
        _shadow_binding_for_session(workspace_file, session_id)
        if session_id.strip()
        else str(result["result"].get("resolved", {}).get("resolution_confidence", "") or "")
    )
    return result


def _sniff_sync(workspace_file: str | Path, intent: str, *, limit: int, task_id: str, title: str, auto_sync_mode: str) -> dict[str, Any]:
    from memory_center.core.orchestrator.sync import workspace_sync_sniff_to_artifacts

    return workspace_sync_sniff_to_artifacts(
        workspace_file, intent, limit=limit, task_id=task_id, title=title, auto_sync_mode=auto_sync_mode
    )


def build_close_shadow_guidance(workspace_file: str | Path, session_id: str) -> dict[str, Any]:
    """close 时的一次性 binding/promotion 建议（不创建 task space）。"""
    shadow_id = shadow_id_for_session(session_id)
    promotion_options: list[dict[str, Any]] = []
    binding_recommendation: dict[str, Any] = {}
    try:
        shadow_state = build_merged_shadow(workspace_file, shadow_id)
    except Exception:
        shadow_state = None
    if shadow_state is None:
        return {"binding_recommendation": {"recommendation": "unavailable"}, "promotion_options": []}
    candidates = shadow_state.get("merged", {}).get("candidate_tasks", []) or []
    if shadow_state.get("binding_status") == "bound":
        binding_recommendation = {
            "recommendation": "promote",
            "shadow_id": shadow_id,
            "bound_task_id": shadow_state.get("bound_task_id", ""),
            "reason": "shadow already bound; promote merges shadow summary/evidence into the task",
        }
        promotion_options.append({
            "option": 1,
            "action": "task_shadow_promote",
            "shadow_id": shadow_id,
            "task_id": shadow_state.get("bound_task_id", ""),
            "description": "把 Shadow 摘要与 evidence 合并进已绑定 task（验证通过后）",
        })
    elif candidates:
        binding_recommendation = {
            "recommendation": "bind",
            "shadow_id": shadow_id,
            "candidate_task_ids": [str(item.get("task_id", "")) for item in candidates[:3] if isinstance(item, dict)],
            "reason": "有候选任务且未绑定；显式绑定后才写入 L2",
        }
    else:
        binding_recommendation = {
            "recommendation": "keep_shadow",
            "shadow_id": shadow_id,
            "reason": "无候选任务；保留为临时工作影子（默认）",
        }
    promotion_options.append({
        "option": len(promotion_options) + 1,
        "action": "keep_shadow",
        "shadow_id": shadow_id,
        "description": "保留为临时工作影子（默认；retention 按未绑定清理）",
    })
    return {"binding_recommendation": binding_recommendation, "promotion_options": promotion_options}


def resolve_close_task_id(workspace_file: str | Path, session_id: str, explicit_task_id: str) -> tuple[str, str]:
    """P1-B 语义：显式参数 > session 绑定 > 空。"""
    close_task_id = (explicit_task_id or "").strip()
    if close_task_id:
        return close_task_id, "explicit"
    try:
        session = workspace_session_summary(workspace_file, session_id)
        close_task_id = str((session.get("summary") or {}).get("task_id", "") or "")
    except Exception:
        close_task_id = ""
    return close_task_id, ("session_binding" if close_task_id else "")


def close_case_records(
    workspace_file: str | Path,
    session_id: str,
    *,
    close_task_id: str,
    title: str,
    auto_sync_mode: str,
    outcome: str,
    record_case: bool,
    verified_by: list[str] | None,
) -> dict[str, Any]:
    """close 的同步与 case 记录聚合（mc_close 复用）。"""
    synced = workspace_sync_case_to_artifacts(
        workspace_file, session_id, task_id=close_task_id, title=title, auto_sync_mode=auto_sync_mode
    )
    draft = workspace_suggest_case(workspace_file, session_id)
    recorded = None
    case = draft.get("draft_case", {}) if draft.get("found") else {}
    if record_case and case.get("projects") and case.get("files"):
        from memory_center.core.orchestrator.write import workspace_record_case

        recorded = workspace_record_case(
            workspace_file,
            case.get("task", outcome or "mc-close"),
            case.get("projects", []),
            case.get("files", []),
            case.get("flow", ""),
            case.get("risk_points", []),
            verified_by=case.get("verified_by", []) or verified_by,
            source_session_id=session_id,
            source_task_id=close_task_id,
        )
    candidate_feedback = workspace_record_close_feedback(
        workspace_file, session_id, task_id=close_task_id, source="mc_close_auto"
    )
    return {"synced": synced, "draft": draft, "recorded": recorded, "candidate_feedback": candidate_feedback}


__all__ = [
    "shadow_id_for_session",
    "shadow_only_sync",
    "case_sync_with_shadow",
    "sniff_sync_with_shadow_fallback",
    "build_close_shadow_guidance",
    "resolve_close_task_id",
    "close_case_records",
]
