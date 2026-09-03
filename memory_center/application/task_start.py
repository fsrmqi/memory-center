"""任务启动用例：计划、定向刷新、工作区嗅探、同步与会话创建。"""
from __future__ import annotations

import time
from typing import Any

from memory_center.core.freshness.integration import get_freshness_with_actions
from memory_center.core.freshness.targeted_refresh import refresh_query_targets
from memory_center.core.governance.templates import get_workflow_guidance
from memory_center.core.orchestrator import workspace_sniff, workspace_start_session, workspace_sync_sniff_to_artifacts
from memory_center.core.retrieval.planner import QueryPlanner


def start_task(workspace_file: str, intent: str, *, limit: int, auto_sync_mode: str, sync_task_space: bool, budget: str, deadline_ms: int, request_tier: str) -> dict[str, Any]:
    planner = QueryPlanner(workspace_file)
    plan = planner.plan(tier=request_tier, limit=limit)
    started_at = time.perf_counter()
    limit, deadline_ms = plan.limit, min(deadline_ms, plan.deadline_ms)
    if plan.tier == "fast":
        budget = "small"
    try:
        auto_refresh = refresh_query_targets(workspace_file, intent, limit=min(limit, 12))
    except Exception:
        auto_refresh = {"checked": 0, "refreshed": False, "files": [], "elapsed_ms": 0.0, "mode": "unavailable", "coalesced": False}
    sniff = workspace_sniff(workspace_file, intent, limit=limit, auto_sync_mode=auto_sync_mode, view="compact", budget=budget, deadline_ms=deadline_ms)
    resolved_task = sniff.get("resolved_task", {}) or {}
    auto_sync = sniff.get("auto_sync_recommendation", {}) or {}
    synced: dict[str, Any] | None = None
    if sync_task_space and (auto_sync.get("recommended") or resolved_task.get("task_id")):
        synced = workspace_sync_sniff_to_artifacts(workspace_file, intent, limit=limit, task_id=str(resolved_task.get("task_id", "") or ""), title=str(resolved_task.get("title", "") or ""), auto_sync_mode=auto_sync_mode, sniff_result=sniff)
    try:
        freshness = get_freshness_with_actions(workspace_file)
    except Exception:
        freshness = {"status": "unknown", "recommended_actions": [], "semantics": ""}
    # P2-C: 标记这是启动时快照；后续查询以 index_context.generation 为准。
    freshness["freshness_snapshot"] = True
    if str(freshness.get("status", "")) in ("stale", "pending"):
        freshness["guidance"] = "本状态是任务启动时的快照；后台定向刷新完成后，后续 mc_lookup 的 index_context.generation 才是当前事实，勿把 stale banner 当作最新查询结论。"
    # P1-B: 绑定本会话解析出的 task，mc_close 优先复用，避免关闭时重新解析
    # 走向错误 task space 污染追加保护工件。
    bound_task_id = ""
    if synced and synced.get("synced"):
        bound_task_id = str(synced.get("task_id", "") or "")
    else:
        bound_task_id = str(resolved_task.get("task_id", "") or "")
    # P2-C: 记录快照 generation，供后续 lookup 检测 stale_to_fresh 转换。
    session_metadata: dict[str, Any] = {}
    if bound_task_id:
        session_metadata["task_id"] = bound_task_id
    session_metadata["freshness_generation"] = str(freshness.get("observed_generation", "") or "")
    session = workspace_start_session(workspace_file, intent, metadata=session_metadata)
    # Session-first: mc_start 自动创建/续接 Task Shadow（L1），不写 L2。
    # 即使 auto_write_allowed=false，Shadow 仍正常更新（提案第 5 节写入分级）。
    from memory_center.core.tasks.shadow import bind_shadow_to_task, build_merged_shadow, ensure_shadow_for_session

    try:
        session_id = str(session.get("session_id", "") or "")
        shadow = ensure_shadow_for_session(workspace_file, session_id, intent=intent)
        if bound_task_id:
            # 显式解析成功（synced 或强解析）才落 bound；否则保持 unbound/suggested
            bind_result = bind_shadow_to_task(
                workspace_file, str(shadow["shadow_id"]), bound_task_id, source="mc_start"
            )
            shadow["binding_status"] = "bound" if bind_result.get("bound") else shadow.get("binding_status", "unbound")
        else:
            resolved_task_row = sniff.get("resolved_task", {}) or {}
            raw_candidates = resolved_task_row.get("candidates") or sniff.get("resolved_candidates") or []
            candidates = [
                {
                    "task_id": str(item.get("task_id", "") or ""),
                    "title": str(item.get("title", "") or ""),
                    "score": item.get("score", 0),
                }
                for item in list(raw_candidates)[:3]
                if isinstance(item, dict) and item.get("task_id")
            ]
            shadow["candidate_tasks"] = candidates
        shadow_state = build_merged_shadow(workspace_file, str(shadow["shadow_id"])) or {}
    except Exception as exc:  # fail-soft: shadow 故障不阻断 start
        shadow = {"shadow_id": "", "error": str(exc)[:160]}
        shadow_state = {}
    return {"workflow": "mc-start", "request_tier": plan.tier, "query_plan": planner.record("mc_start", plan, started_at, outcome="completed"), "sniff": sniff, "sync_sniff": synced, "session": session, "auto_refresh": auto_refresh, "_workflow_guidance": get_workflow_guidance("work-start", {"risk_level": sniff.get("risk_level", ""), "task_id": bound_task_id}), "freshness": freshness, "bound_task_id": bound_task_id, "task_shadow": shadow, "shadow_summary": {"binding_status": shadow_state.get("binding_status", ""), "candidate_tasks": shadow_state.get("merged", {}).get("candidate_tasks", [])[:3], "shadow_id": shadow_state.get("shadow_id", "")}}
