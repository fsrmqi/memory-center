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


def _chain_gate_from_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    """P1-A: extract the chain anchor/scope validation from a chain result.

    ``payload["result"]`` 是 memory_callers/memory_callees/group_chain 的返回。
    有锚点校验时把 status 与 scope_incomplete 传给 claim boundary；无校验
    字段（旧结果或非 chain 路由）返回 None，不影响其它模式。
    """
    result = payload.get("result")
    if not isinstance(result, dict):
        return None
    anchor_validation = result.get("chain_anchor_validation")
    if not isinstance(anchor_validation, dict):
        return None
    scope = result.get("chain_scope_validation")
    return {
        "anchor_status": str(anchor_validation.get("status", "missing")),
        "scope_incomplete": bool(isinstance(scope, dict) and scope.get("scope_incomplete")),
    }


def _freshness_transition_note(payload: dict[str, Any], session_id: str) -> None:
    """P2-C: 当查询 generation 与任务启动快照不同，返回 freshness_transition。

    Agent 据此知道旧 stale banner 已被后台刷新取代（stale_to_fresh），
    不再把启动快照当作当前查询事实。静默失败不影响查询结果。
    """
    index_context = payload.get("index_context")
    if not isinstance(index_context, dict) or not str(session_id or "").strip():
        return
    try:
        from memory_center.core.freshness.contract import freshness_transition
        from memory_center.core.orchestrator.session import workspace_session_summary

        summary = workspace_session_summary(str(payload.get("_workspace_file", "")), session_id)
        events = summary.get("events", []) if summary.get("found") else []
        observed = ""
        for event in events or []:
            if event.get("event_type") == "session_start":
                observed = str((event.get("payload") or {}).get("freshness_generation", "") or "")
                break
        if not observed:
            return
        transition = freshness_transition(index_context, observed)
        if transition:
            payload["freshness_transition"] = transition
    except Exception:
        return


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
    from memory_center.core.freshness.contract import attach_contract

    template_budget = payload.get("query_budget") if isinstance(payload.get("query_budget"), dict) else None
    attach_contract(
        payload,
        workspace_file,
        request_tier=plan.tier,
        query_budget=template_budget,
        project=str(getattr(plan, "project", "") or ""),
        chain_gate=_chain_gate_from_payload(payload),
    )
    # Primary cross-service chain (additive): only for a Method anchor from
    # the symbol path. Never fabricates — status is found/not_found/
    # insufficient_evidence/truncated and callers must phrase accordingly.
    result = payload.get("result")
    best_match = result.get("best_match") if isinstance(result, dict) else None
    if isinstance(best_match, dict) and str(best_match.get("type", "")).startswith("Method"):
        try:
            from memory_center.core.retrieval.primary_chain import find_primary_service_chain

            # fast tier: skip the cross-service search (keeps P95 flat);
            # standard/deep: bounded cross-service search. Feign chains need
            # 3 steps (entry -> FeignMethod -> Endpoint), so depth stays 3;
            # the node budget keeps it cheap.
            if plan.tier != "fast":
                payload["primary_chain"] = find_primary_service_chain(
                    workspace_file,
                    best_match,
                    project=str(getattr(plan, "project", "") or ""),
                    max_depth=3,
                )
        except Exception:
            payload["primary_chain"] = {
                "status": "insufficient_evidence",
                "reason_codes": ["primary_chain_unavailable"],
                "steps": [],
                "score": 0.0,
                "evidence_level": "AMBIGUOUS",
                "generation": "",
            }
    from memory_center.core.knowledge.governance import record_actions
    from memory_center.core.knowledge.state import attach_knowledge_state
    from memory_center.core.storage.workspace import WorkspaceStore

    attach_knowledge_state(
        WorkspaceStore(workspace_file),
        payload,
        query=target,
        project=str(getattr(plan, "project", "") or ""),
        mode=operation,
    )
    store = WorkspaceStore(workspace_file)
    actions = record_actions(store, origin=f"{operation}:{target}", actions=list(payload.get("agent_next_steps", []) or []))
    if actions:
        payload["agent_actions"] = actions
    payload["_workspace_file"] = str(workspace_file)
    _freshness_transition_note(payload, str(payload.get("_lookup_session_id", "")))
    payload.pop("_workspace_file", None)
    payload.pop("_lookup_session_id", None)
    return payload
