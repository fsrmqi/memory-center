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


def session_task_binding(workspace_file: str | Path, session_id: str) -> dict[str, Any]:
    """Read the immutable binding decision recorded at session start."""
    try:
        session = workspace_session_summary(workspace_file, session_id)
    except Exception:
        return {"mode": "shadow_only", "task_id": ""}
    for event in session.get("events", []):
        if not isinstance(event, dict) or event.get("event_type") != "session_start":
            continue
        payload = event.get("payload", {})
        decision = payload.get("task_binding", {}) if isinstance(payload, dict) else {}
        if isinstance(decision, dict) and decision.get("mode") == "auto_direct_anchor" and decision.get("task_id"):
            return {"mode": "auto_direct_anchor", "task_id": str(decision["task_id"])}
    return {"mode": "shadow_only", "task_id": ""}


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
        decision = session_task_binding(workspace_file, session_id)
        if decision.get("task_id"):
            resolved_task_id = str(decision["task_id"])
            resolved_source = "session_binding"
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
    """intent 维度的 sniff sync：低置信解析时更新 Shadow 而不放弃连续性。

    L2 写入门禁（P1）：`auto` 模式同样只在显式 task_id 或可验证的 bound
    Shadow 时才允许 sniff sync 解析/创建 task space；否则不调用
    _sniff_sync（其底层以 create_if_missing=True 会自行创建 L2），直接
    走 shadow_only_sync。
    """
    resolved_task_id = (task_id or "").strip()
    resolved_source = "explicit" if resolved_task_id else ""
    if not resolved_task_id and session_id.strip():
        shadow = build_merged_shadow(workspace_file, shadow_id_for_session(session_id))
        if shadow is not None and shadow.get("binding_status") == "bound":
            resolved_task_id = str(shadow.get("bound_task_id", "") or "")
            resolved_source = "shadow_binding"
    if not resolved_task_id:
        fallback = shadow_only_sync(
            workspace_file,
            session_id or f"anon-{abs(hash(intent)) % 10**10}",
            intent,
            "shadow_not_bound: provide explicit task_id or bind the shadow before writing L2",
        )
        fallback["mode"] = "sniff"
        return fallback
    result: dict[str, Any] = {
        "workflow": "mc-sync",
        "mode": "sniff",
        "result": _sniff_sync(
            workspace_file,
            intent,
            limit=limit,
            task_id=resolved_task_id,
            title=title,
            auto_sync_mode=auto_sync_mode,
        ),
    }
    if result["result"].get("synced"):
        result["write_target"] = "task_space"
    else:
        # 显式 task_id 或 bound Shadow 下 sniff 仍可能因内部契约失败返回
        # 未同步（不会自行创建 L2）；此时仅记录，不重写为 shadow 模式以免
        # 掩盖真实的显式意图。
        result["write_target"] = "none"
    result["binding_status"] = (
        _shadow_binding_for_session(workspace_file, session_id)
        if session_id.strip()
        else str(result["result"].get("resolved", {}).get("resolution_confidence", "") or "")
    )
    result["task_id_source"] = resolved_source
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
    decision = session_task_binding(workspace_file, session_id)
    if decision.get("task_id"):
        return str(decision["task_id"]), "session_binding"
    shadow = build_merged_shadow(workspace_file, shadow_id_for_session(session_id))
    if shadow is not None and shadow.get("binding_status") == "bound" and shadow.get("bound_task_id"):
        return str(shadow["bound_task_id"]), "shadow_binding"
    return "", ""


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
    """close 的同步与 case 记录聚合（mc_close 复用）。

    P0 自写自匹配修复：无显式 task_id 且解析低置信/歧义时，同步降级为
    shadow-only（不写 L2），避免无关 intent 被吸进既有 task space 形成轮替。
    """
    synced = workspace_sync_case_to_artifacts(
        workspace_file, session_id, task_id=close_task_id, title=title, auto_sync_mode=auto_sync_mode
    )
    # 低置信解析保护：close 自动路径不允许把低分/歧义解析写进 L2。
    if (
        not close_task_id
        and synced.get("synced") is False
        and synced.get("reason") in ("task_resolution_not_auto_writable", "failed_to_resolve_task_space")
    ):
        synced = {
            **synced,
            "fallback": "shadow_only",
            "hint": "解析低置信或歧义：本次 close 不写 L2，会话证据保留在 Shadow/notes 中；可显式 task_id 重试。",
        }
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
            actor="mc_close_agent",
            decision_reason="mc_close_auto_case",
        )
    candidate_feedback = workspace_record_close_feedback(
        workspace_file, session_id, task_id=close_task_id, source="mc_close_auto"
    )
    # L0.5 Session Notes: deterministic drafts are always surfaced as
    # suggestions; nothing is persisted here without explicit confirmation
    # (mc_admin action="note_record" per draft).
    note_drafts: list[dict[str, Any]] = []
    try:
        from memory_center.core.orchestrator.session import workspace_session_summary
        from memory_center.core.tasks.session_notes import draft_notes_from_session

        session_detail = workspace_session_summary(workspace_file, session_id)
        note_drafts = draft_notes_from_session(
            workspace_file,
            session_id,
            summary=session_detail.get("summary") if isinstance(session_detail.get("summary"), dict) else {},
            events=session_detail.get("events", []) if isinstance(session_detail.get("events"), list) else [],
        )
    except Exception:
        note_drafts = []
    return {
        "synced": synced,
        "draft": draft,
        "recorded": recorded,
        "candidate_feedback": candidate_feedback,
        "note_drafts": note_drafts,
        "note_drafts_hint": "确认后用 mc_admin(action=\"note_record\", text=..., event_type=kind, session_id=...) 逐条入库；未确认的草稿不会落盘。",
    }


__all__ = [
    "shadow_id_for_session",
    "session_task_binding",
    "shadow_only_sync",
    "case_sync_with_shadow",
    "sniff_sync_with_shadow_fallback",
    "build_close_shadow_guidance",
    "resolve_close_task_id",
    "close_case_records",
]
