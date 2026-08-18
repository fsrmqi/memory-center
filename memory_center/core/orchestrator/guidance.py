"""Agent 下一步建议(agent_next_steps)构建与 adoption/replay 反馈增强。

从 query.py 按独立职责拆出的 agent 指导辅助(ADR-0002)。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def _build_agent_next_steps_for_walkthrough(result: dict[str, Any]) -> list[dict[str, Any]]:
    status = result.get("completion_status", {}) if isinstance(result.get("completion_status", {}), dict) else {}
    policy = result.get("agent_usage_policy", {}) if isinstance(result.get("agent_usage_policy", {}), dict) else {}
    freshness = result.get("index_freshness", {}) if isinstance(result.get("index_freshness", {}), dict) else {}
    if bool(freshness.get("index_stale")):
        return [
            {
                "action": "read_live_stale_targets",
                "priority": "high",
                "reason": "walkthrough target index is stale; live file evidence must win before editing",
                "command": "read files from index_freshness.stale_read_targets",
                "uses_existing_evidence": True,
            }
        ]
    if status.get("recommended_action") == "use_current_evidence" and policy.get("do_not_search_when_absolute_path_present"):
        return [
            {
                "action": "use_read_targets",
                "priority": "high",
                "reason": "walkthrough is complete and already includes absolute_file_path read targets",
                "command": "read read_targets[].absolute_file_path directly; do not run find/grep-l for the same symbols",
                "uses_existing_evidence": True,
            }
        ]
    if status.get("state") in {"partial", "blocked"}:
        return [
            {
                "action": "fill_missing_walkthrough_layers",
                "priority": "high",
                "reason": str(status.get("reason", "") or "walkthrough is not complete"),
                "command": "inspect completion_status.missing_layers and then rerun mc_lookup(mode='walkthrough') if needed",
                "uses_existing_evidence": True,
            }
        ]
    return [
        {
            "action": "continue_with_current_evidence",
            "priority": "medium",
            "reason": "walkthrough returned bounded indexed evidence",
            "command": "summarize from summary_lines/read_targets before using broader search",
            "uses_existing_evidence": True,
        }
    ]


def _build_agent_next_steps_for_query(result: dict[str, Any], *, query: str, workspace_file: str | Path | None = None) -> list[dict[str, Any]]:
    freshness_status = str(((result.get("freshness", {}) or {}).get("freshness", {}) or {}).get("status", "unknown"))
    policy = result.get("retrieval_policy", {}) if isinstance(result.get("retrieval_policy", {}), dict) else {}
    diagnostics = result.get("retrieval_diagnostics", {}) if isinstance(result.get("retrieval_diagnostics", {}), dict) else {}
    results = result.get("results", []) if isinstance(result.get("results", []), list) else []
    vector = diagnostics.get("vector", {}) if isinstance(diagnostics.get("vector", {}), dict) else {}
    if vector.get("status") == "unavailable" and int(vector.get("embedding_count", 0) or 0) > 64:
        return _apply_agent_guidance_adoption_feedback(workspace_file, [
            {
                "action": "rebuild_vector_ann",
                "priority": "high",
                "reason": "dense embeddings exist but the persistent ANN index is unavailable; large indexes must not use exact fallback",
                "command": "mc_admin(action='vector_ann_rebuild') then mc_admin(action='vector_ann_tune')",
                "uses_existing_evidence": False,
                "stop_condition": "vector_ann_status reports ann_ready=true",
                "failure_fallback": "continue with BM25/graph retrieval and report ANN unavailable",
            }
        ])
    if freshness_status in {"stale", "pending"}:
        return _apply_agent_guidance_adoption_feedback(workspace_file, [
            {
                "action": "refresh_or_read_live_files",
                "priority": "high",
                "reason": f"index freshness is {freshness_status}; indexed hits may be outdated",
                "command": "read matched files live before editing; run memory-center reindex when freshness affects the target",
                "uses_existing_evidence": True,
            }
        ])
    if not results:
        return _apply_agent_guidance_adoption_feedback(workspace_file, [
            {
                "action": "refine_query",
                "priority": "medium",
                "reason": "hybrid retrieval returned no evidence",
                "command": "retry mc_lookup with a class, method, endpoint, Feign client, or business term from the task",
                "uses_existing_evidence": False,
            }
        ])
    top = results[0].get("node", results[0]) if isinstance(results[0], dict) else {}
    top_type = str(top.get("type", "") or "")
    top_name = str(top.get("name", "") or query)
    target_hint = _agent_next_step_target_hint(results[0])
    if top_type in {"Method", "FeignMethod"} or "#" in query:
        return _apply_agent_guidance_adoption_feedback(workspace_file, [
            {
                "action": "switch_to_walkthrough",
                "priority": "high",
                "reason": "method-level evidence is available; walkthrough gives bounded chain and read targets",
                "command": f'mc_lookup(query="{top_name}", mode="walkthrough")',
                "uses_existing_evidence": True,
                **target_hint,
            }
        ])
    if diagnostics.get("semantic", {}).get("status") == "active" and policy.get("primary_intent") == "general":
        return _apply_agent_guidance_adoption_feedback(workspace_file, [
            {
                "action": "validate_semantic_hit",
                "priority": "medium",
                "reason": "top results include semantic retrieval; verify the top file or symbol before assuming exact relevance",
                "command": "open the top result file or rerun mc_lookup with a concrete symbol from the hit",
                "uses_existing_evidence": True,
                **target_hint,
            }
        ])
    return _apply_agent_guidance_adoption_feedback(workspace_file, [
        {
            "action": "inspect_top_result",
            "priority": "medium",
            "reason": "hybrid retrieval returned indexed evidence",
            "command": "read the top result file/symbol, then call mc_analyze before editing shared contracts",
            "uses_existing_evidence": True,
            **target_hint,
        }
    ])


def _apply_agent_guidance_adoption_feedback(workspace_file: str | Path | None, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not workspace_file or not steps:
        return steps
    try:
        from ..benchmark.trending import get_agent_guidance_adoption_trends, get_agent_guidance_replay_trends

        adoption_trends = get_agent_guidance_adoption_trends(workspace_file, limit=20)
        replay_trends = get_agent_guidance_replay_trends(workspace_file, limit=20)
    except Exception:
        return steps
    adoption_counts: dict[str, Any] = {}
    if adoption_trends.get("regressions"):
        summary = adoption_trends.get("summary", {}) if isinstance(adoption_trends.get("summary", {}), dict) else {}
        latest_counts = summary.get("latest_missed_action_counts", {})
        if isinstance(latest_counts, dict):
            adoption_counts = latest_counts
    replay_reason_counts = _latest_replay_reason_counts(replay_trends) if replay_trends.get("regressions") else {}
    if not adoption_counts and not replay_reason_counts:
        return steps
    adjusted: list[dict[str, Any]] = []
    for step in steps:
        reinforced = dict(step)
        action = str(step.get("action", "") or "")
        missed_count = int(adoption_counts.get(action, 0) or 0)
        if missed_count > 0:
            reinforced["priority"] = "high"
            reinforced["adoption_feedback"] = {
                "status": "reinforced",
                "missed_count": missed_count,
                "reason": "recent adoption trend shows this action was often missed",
            }
            reinforced["command"] = _append_agent_feedback_command(
                reinforced.get("command", ""),
                "low-adoption feedback",
                _reinforced_agent_command(action),
            )
        if replay_reason_counts:
            reinforced = _apply_agent_guidance_replay_feedback(reinforced, replay_reason_counts)
        adjusted.append(reinforced)
    return adjusted


def _agent_next_step_target_hint(result: dict[str, Any]) -> dict[str, Any]:
    node = result.get("node", result) if isinstance(result, dict) else {}
    if not isinstance(node, dict):
        return {}
    target_ref = str(node.get("abs_path") or node.get("absolute_file_path") or node.get("file_path") or node.get("path") or "")
    if not target_ref:
        return {}
    hint: dict[str, Any] = {
        "target_ref": target_ref,
        "read_targets": [target_ref],
    }
    symbol = str(node.get("name", "") or "")
    if symbol:
        hint["target_symbol"] = symbol
    return hint


def _latest_replay_reason_counts(trends: dict[str, Any]) -> dict[str, int]:
    points = trends.get("trend_points", [])
    latest = points[-1] if isinstance(points, list) and points else {}
    raw_counts = latest.get("reason_counts", {}) if isinstance(latest, dict) else {}
    if not isinstance(raw_counts, dict) or not raw_counts:
        summary = trends.get("summary", {}) if isinstance(trends.get("summary", {}), dict) else {}
        raw_counts = summary.get("reason_counts", {})
    if not isinstance(raw_counts, dict):
        return {}
    return {
        str(reason): int(count or 0)
        for reason, count in raw_counts.items()
        if str(reason) and int(count or 0) > 0
    }


def _apply_agent_guidance_replay_feedback(step: dict[str, Any], reason_counts: dict[str, int]) -> dict[str, Any]:
    dominant_reason = max(reason_counts.items(), key=lambda item: item[1])[0] if reason_counts else ""
    if not dominant_reason:
        return step
    action = str(step.get("action", "") or "")
    reinforced = dict(step)
    reinforced["priority"] = "high"
    reinforced["replay_feedback"] = {
        "status": "reinforced",
        "dominant_reason": dominant_reason,
        "reason_count": int(reason_counts.get(dominant_reason, 0) or 0),
        "reason_counts": reason_counts,
    }
    if dominant_reason == "guidance_missing_target_hint":
        reinforced["target_required"] = True
    reinforced["command"] = _append_agent_feedback_command(
        reinforced.get("command", ""),
        "replay feedback",
        _reinforced_replay_command(action, dominant_reason),
    )
    return reinforced


def _append_agent_feedback_command(command: Any, label: str, addition: str) -> str:
    base = str(command or "").strip()
    if not base:
        return f"{label}: {addition}"
    if addition in base:
        return base
    return f"{base}; {label}: {addition}"


def _reinforced_agent_command(action: str) -> str:
    if action == "inspect_top_result":
        return "first read result[0].node.file_path or result[0].node.abs_path directly; if no path is present, call mc_lookup(mode='context') with the top symbol"
    if action == "validate_semantic_hit":
        return "open the top result file before reasoning; if relevance is unclear, rerun mc_lookup(mode='query') with the concrete symbol from that hit"
    if action == "switch_to_walkthrough":
        return "call mc_lookup(mode='walkthrough') immediately with the returned method-like symbol, before any broad search"
    if action == "refine_query":
        return "retry mc_lookup(mode='query') with one concrete class, method, endpoint, Feign client, config key, or business term"
    if action == "refresh_or_read_live_files":
        return "read the matched live files first, then run memory-center reindex only if stale evidence affects the target"
    return "execute this exact Memory Center next step before trying a broader local search"


def _reinforced_replay_command(action: str, reason: str) -> str:
    if reason == "local_search_or_non_memory_tool_used":
        return "execute the Memory Center command in this step before rg/grep/find; only use local search after the returned target is missing or stale"
    if reason == "no_followup_tool_call":
        return "provide a session_id to mc_lookup/query and make the next tool call observable before continuing"
    if reason == "guidance_missing_target_hint":
        if action in {"inspect_top_result", "validate_semantic_hit", "refresh_or_read_live_files", "use_read_targets"}:
            return "use read_targets[0] or target_ref from this step as the first file/symbol to inspect"
        return "include the exact target symbol or target_ref when executing this step"
    if reason == "memory_tool_used_but_action_mismatch":
        return "call the Memory Center tool that matches this action instead of a different lookup mode"
    if reason == "guidance_missing_executable_command":
        return "run the command in this step exactly; if unavailable, call mc_lookup with the same action intent"
    return "follow this Memory Center next step exactly before trying an alternate path"
