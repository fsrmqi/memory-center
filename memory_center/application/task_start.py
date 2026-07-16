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
    return {"workflow": "mc-start", "request_tier": plan.tier, "query_plan": planner.record("mc_start", plan, started_at, outcome="completed"), "sniff": sniff, "sync_sniff": synced, "session": workspace_start_session(workspace_file, intent), "auto_refresh": auto_refresh, "_workflow_guidance": get_workflow_guidance("work-start", {"risk_level": sniff.get("risk_level", ""), "task_id": resolved_task.get("task_id", "")}), "freshness": freshness}
