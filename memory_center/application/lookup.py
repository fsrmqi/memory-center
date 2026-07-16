"""查询任务的规划、刷新、跨分片路由与融合。"""
from __future__ import annotations

import time
from typing import Any

from memory_center.core.freshness.targeted_refresh import refresh_query_targets
from memory_center.core.retrieval.cross_service import query_cross_service_shards, route_cross_service_shards
from memory_center.core.retrieval.cross_service_fusion import fuse_cross_shard_result
from memory_center.core.retrieval.planner import QueryPlanner


def prepare_lookup(workspace_file: str, target: str, *, request_tier: str, limit: int, depth: int, enable_vector: bool, project: str) -> dict[str, Any]:
    planner = QueryPlanner(workspace_file)
    plan = planner.plan(tier=request_tier, limit=limit, depth=depth, enable_vector=enable_vector, project=project)
    started_at = time.perf_counter()
    try:
        route = route_cross_service_shards(workspace_file, target, tier=plan.tier, project=project)
        evidence = query_cross_service_shards(workspace_file, target, route, limit=plan.limit)
    except Exception:
        route = {"available": False, "reason": "routing_unavailable", "selected_projects": []}
        evidence = {"queried_projects": [], "matches": [], "source": "unavailable"}
    try:
        refresh = refresh_query_targets(workspace_file, target, limit=min(plan.limit, 12))
    except Exception:
        refresh = {"checked": 0, "refreshed": False, "files": [], "elapsed_ms": 0.0, "mode": "unavailable", "coalesced": False}
    return {"planner": planner, "plan": plan, "started_at": started_at, "auto_refresh": refresh, "shard_route": route, "shard_evidence": evidence}


def finalize_lookup(workspace_file: str, target: str, payload: dict[str, Any], prepared: dict[str, Any], operation: str) -> dict[str, Any]:
    plan = prepared["plan"]
    payload["auto_refresh"] = prepared["auto_refresh"]
    payload["request_tier"] = plan.tier
    payload["query_plan"] = prepared["planner"].record(operation, plan, prepared["started_at"], outcome="completed")
    payload["shard_route"] = prepared["shard_route"]
    payload["shard_evidence"] = prepared["shard_evidence"]
    try:
        payload["cross_shard_fusion"] = fuse_cross_shard_result(workspace_file, target, payload, prepared["shard_route"], prepared["shard_evidence"])
    except Exception:
        payload["cross_shard_fusion"] = {"generation": {"consistent": False, "status": "fusion_unavailable"}, "conclusions": [], "next_actions": []}
    return payload
