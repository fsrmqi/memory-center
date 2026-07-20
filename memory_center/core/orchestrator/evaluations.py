from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any

from memory_center.core.assessment.evals import EvalResultBuilder
from memory_center.core.foundation.schemas import with_schema
from memory_center.core.foundation.tokens import estimate_tokens
from memory_center.core.retrieval.semantic import semantic_index_stats

from .shared import (
    LAYER_L0,
    LAYER_L1,
    LAYER_L2,
    LAYER_L3,
    SESSION_EVENTS_FILE,
    _event_payload,
    _load_eval_rules,
    load_context,
)
from .write import workspace_replay_write_chain


def memory_eval_write_quality(
    workspace_file: str | Path,
    task_id: str = "",
    session_id: str = "",
    intent: str = "",
    limit: int = 100,
) -> dict[str, Any]:
    config, store = load_context(workspace_file)
    replay = workspace_replay_write_chain(workspace_file, task_id=task_id, session_id=session_id, limit=limit)
    receipts = replay.get("timeline", [])
    layers = {item.get("layer", "") for item in receipts}
    builder = EvalResultBuilder()
    penalties = (_load_eval_rules(store).get("write_quality", {}) or {}).get("penalties", {})
    rule_keywords = [str(item).lower() for item in ((_load_eval_rules(store).get("write_quality", {}) or {}).get("rule_intent_keywords", []) or [])]

    has_l0 = LAYER_L0 in layers
    has_l1 = LAYER_L1 in layers
    has_l2 = LAYER_L2 in layers
    has_l3 = LAYER_L3 in layers

    if session_id and not has_l0:
        builder.add("medium", "missing_l0", "存在 session_id，但没有对应的 L0 会话事件写入。", int(penalties.get("missing_l0", 20)))
    if task_id and not has_l2:
        builder.add("high", "missing_l2", "存在 task_id，但没有对应的 L2 任务空间写入。", int(penalties.get("missing_l2", 30)))
    if session_id and not has_l1:
        builder.add("medium", "missing_l1", "存在 session_id，但没有沉淀为 L1 case memory。", int(penalties.get("missing_l1", 15)))
    if any(keyword in intent.lower() for keyword in rule_keywords):
        if not has_l3:
            builder.add("medium", "missing_l3", "意图看起来属于规则/规范类，但没有对应的 L3 核心记忆块写入。", int(penalties.get("missing_l3", 20)))
    if not receipts:
        builder.add("high", "no_receipts", "没有找到任何 write receipts，无法证明记忆写入链路已执行。", int(penalties.get("no_receipts", 100)))

    return builder.finalize(
        workspace=config.workspace,
        task_id=task_id,
        session_id=session_id,
        intent=intent,
        receipt_count=len(receipts),
        layers_present=sorted(layer for layer in layers if layer),
        replay_summary=replay.get("summary", {}),
    )


def memory_eval_resume(
    workspace_file: str | Path,
    task_id: str = "",
    session_id: str = "",
    intent: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    from .resume import workspace_resume_packet  # lazy import

    config, store = load_context(workspace_file)
    packet = workspace_resume_packet(workspace_file, task_id=task_id, session_id=session_id, intent=intent, limit=limit)
    builder = EvalResultBuilder()
    penalties = (_load_eval_rules(store).get("resume", {}) or {}).get("penalties", {})

    if not packet.get("current_summary"):
        builder.add("high", "missing_current_summary", "恢复包缺少 current_summary。", int(penalties.get("missing_current_summary", 30)))
    if not packet.get("next_recommended_actions"):
        builder.add("medium", "missing_next_actions", "恢复包缺少 next_recommended_actions。", int(penalties.get("missing_next_actions", 20)))
    if "unresolved_items" not in packet:
        builder.add("medium", "missing_unresolved_items", "恢复包缺少 unresolved_items。", int(penalties.get("missing_unresolved_items", 15)))
    if packet.get("verification_pending") and not packet.get("unresolved_items"):
        builder.add("low", "verification_flag_without_items", "verification_pending 为真，但没有明确未解决事项。", int(penalties.get("verification_flag_without_items", 10)))
    if not packet.get("resume_rule_profile"):
        builder.add("low", "missing_resume_rule_profile", "恢复包未声明命中的规则画像。", int(penalties.get("missing_resume_rule_profile", 10)))

    return builder.finalize(
        workspace=config.workspace,
        task_id=packet.get("task_id", ""),
        session_id=session_id,
        intent=intent,
        resume_rule_profile=packet.get("resume_rule_profile", ""),
    )


def memory_eval_handoff(
    workspace_file: str | Path,
    target_model: str,
    task_id: str = "",
    session_id: str = "",
    intent: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    from .resume import workspace_handoff_packet  # lazy import

    config, store = load_context(workspace_file)
    packet = workspace_handoff_packet(
        workspace_file,
        target_model=target_model,
        task_id=task_id,
        session_id=session_id,
        intent=intent,
        limit=limit,
    )
    handoff_body = packet.get("handoff_packet", {})
    builder = EvalResultBuilder()
    penalties = (_load_eval_rules(store).get("handoff", {}) or {}).get("penalties", {})

    if not handoff_body.get("minimal_required_context"):
        builder.add("high", "missing_minimal_context", "交接包缺少 minimal_required_context。", int(penalties.get("missing_minimal_context", 30)))
    if not handoff_body.get("what_to_check_next"):
        builder.add("medium", "missing_next_checks", "交接包缺少 what_to_check_next。", int(penalties.get("missing_next_checks", 20)))
    if not handoff_body.get("what_not_to_repeat"):
        builder.add("medium", "missing_do_not_repeat", "交接包缺少 what_not_to_repeat。", int(penalties.get("missing_do_not_repeat", 15)))
    if not packet.get("handoff_rule_profile"):
        builder.add("low", "missing_handoff_rule_profile", "交接包未声明命中的 handoff 规则画像。", int(penalties.get("missing_handoff_rule_profile", 10)))
    if not packet.get("model_profile", {}).get("normalized_model"):
        builder.add("low", "missing_model_profile", "交接包缺少标准化模型画像。", int(penalties.get("missing_model_profile", 10)))

    return builder.finalize(
        workspace=config.workspace,
        target_model=target_model,
        task_id=packet.get("task_id", ""),
        session_id=session_id,
        handoff_rule_profile=packet.get("handoff_rule_profile", ""),
        normalized_model=packet.get("model_profile", {}).get("normalized_model", ""),
    )


def memory_eval_regression_suite(
    workspace_file: str | Path,
    *,
    task_id: str = "",
    session_id: str = "",
    intent: str = "",
    target_model: str = "codex",
    limit: int = 20,
) -> dict[str, Any]:
    config, _ = load_context(workspace_file)
    write_eval = memory_eval_write_quality(workspace_file, task_id=task_id, session_id=session_id, intent=intent, limit=limit)
    resume_eval = memory_eval_resume(workspace_file, task_id=task_id, session_id=session_id, intent=intent, limit=limit)
    handoff_eval = memory_eval_handoff(
        workspace_file,
        target_model=target_model,
        task_id=task_id,
        session_id=session_id,
        intent=intent,
        limit=limit,
    )
    agent_guidance_eval = memory_eval_agent_guidance(workspace_file, intent=intent, limit=limit)
    agent_guidance_adoption = memory_eval_agent_guidance_adoption(workspace_file, session_id=session_id, limit=limit)
    agent_guidance_replay = memory_eval_agent_guidance_replay(workspace_file, session_id=session_id, limit=limit)
    components = {
        "write_quality": write_eval,
        "resume": resume_eval,
        "handoff": handoff_eval,
        "agent_guidance": agent_guidance_eval,
        "agent_guidance_adoption": agent_guidance_adoption,
        "agent_guidance_replay": agent_guidance_replay,
    }
    scores = [int(item.get("score", 0) or 0) for item in components.values()]
    avg_score = int(sum(scores) / len(scores)) if scores else 0
    suite = with_schema(
        "eval_result",
        {
            "workspace": config.workspace,
            "score": avg_score,
            "quality": "high" if avg_score >= 85 else ("medium" if avg_score >= 60 else "low"),
            "findings": [finding for result in components.values() for finding in result.get("findings", [])],
            "components": components,
            "suite_name": "memory_eval_regression_suite",
            "target_model": target_model,
        },
    )
    return suite


def memory_eval_agent_guidance(
    workspace_file: str | Path,
    *,
    intent: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    """Evaluate whether lookup output gives bounded, actionable next steps."""

    from ..benchmark.golden import evaluate_agent_guidance  # lazy import
    from .query import memory_query_hybrid  # lazy import
    from .workspace_ops import workspace_status  # lazy import

    config, _ = load_context(workspace_file)
    query = intent.strip()
    if not query:
        status = workspace_status(workspace_file, view="compact", budget="small")
        focus = status.get("current_focus_task", {}) or {}
        query = str(focus.get("title", "") or focus.get("summary_preview", "") or "").strip()

    builder = EvalResultBuilder()
    payload: dict[str, Any] = {}
    guidance: dict[str, Any] = evaluate_agent_guidance(payload)
    if not query:
        builder.add("medium", "missing_guidance_query", "缺少 intent 或当前任务标题，无法抽样评估 agent_next_steps。", 25)
    else:
        payload = memory_query_hybrid(workspace_file, query=query, limit=limit)
        guidance = evaluate_agent_guidance(payload)
        if int(guidance.get("agent_next_step_count", 0) or 0) <= 0:
            builder.add("high", "missing_agent_next_steps", "查询结果缺少 agent_next_steps，Agent 无法直接判断下一步。", 35)
        invalid_count = int(guidance.get("invalid_search_suggestion_count", 0) or 0)
        if invalid_count > 0:
            builder.add("high", "invalid_search_suggestions", "agent-facing 建议仍包含低效或无界搜索提示。", 40)
        if not guidance.get("passed", False):
            builder.add("medium", "agent_guidance_gate_failed", "agent guidance 未通过建议质量门禁。", 20)

    return builder.finalize(
        workspace=config.workspace,
        intent=query,
        agent_next_step_count=int(guidance.get("agent_next_step_count", 0) or 0),
        agent_next_step_actions=guidance.get("agent_next_step_actions", []),
        invalid_search_suggestion_count=int(guidance.get("invalid_search_suggestion_count", 0) or 0),
        invalid_search_suggestions=guidance.get("invalid_search_suggestions", []),
        invalid_search_reduction_rate=float(guidance.get("invalid_search_reduction_rate", 0.0) or 0.0),
        passed=bool(guidance.get("passed", False)) and builder.score >= 60,
        sampled_result_summary={
            "result_count": len(payload.get("results", [])) if isinstance(payload.get("results", []), list) else 0,
            "freshness_status": ((payload.get("freshness", {}) or {}).get("freshness", {}) or {}).get("status", ""),
        } if payload else {},
    )


def memory_eval_agent_guidance_trend(
    workspace_file: str | Path,
    *,
    intent: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    """Run agent guidance eval and append one trend point."""

    from ..benchmark.trending import record_agent_guidance_trend

    result = memory_eval_agent_guidance(workspace_file, intent=intent, limit=limit)
    recorded = record_agent_guidance_trend(
        workspace_file,
        intent=str(result.get("intent", "") or intent),
        agent_next_step_count=int(result.get("agent_next_step_count", 0) or 0),
        invalid_search_suggestion_count=int(result.get("invalid_search_suggestion_count", 0) or 0),
        invalid_search_reduction_rate=float(result.get("invalid_search_reduction_rate", 0.0) or 0.0),
        score=int(result.get("score", 0) or 0),
        quality=str(result.get("quality", "") or ""),
        passed=bool(result.get("passed", False)),
        agent_next_step_actions=[
            str(action)
            for action in (result.get("agent_next_step_actions", []) or [])
            if str(action)
        ],
    )
    return {
        **recorded,
        "eval": result,
    }


def memory_eval_agent_guidance_adoption(
    workspace_file: str | Path,
    *,
    session_id: str = "",
    limit: int = 200,
) -> dict[str, Any]:
    """Evaluate whether recorded agent guidance was followed by matching tools."""

    config, store = load_context(workspace_file)
    events = store.read_jsonl_prefer_backend(SESSION_EVENTS_FILE, limit=max(limit, 1))
    if session_id:
        events = [event for event in events if event.get("session_id") == session_id]

    records: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        if event.get("event_type") not in {"agent_guidance", "agent_next_steps"}:
            continue
        payload = _event_payload(event)
        steps = payload.get("agent_next_steps", [])
        if not isinstance(steps, list) or not steps:
            continue
        first_step = next((step for step in steps if isinstance(step, dict) and step.get("action")), None)
        if not first_step:
            continue
        sid = str(event.get("session_id", "") or "")
        action = str(first_step.get("action", "") or "")
        followups = [
            candidate
            for candidate in events[index + 1:]
            if candidate.get("session_id") == sid and candidate.get("event_type") == "tool_call"
        ][:5]
        matched_tool = _match_agent_guidance_followup(action, followups)
        records.append({
            "session_id": sid,
            "query": payload.get("query", "") or payload.get("intent", ""),
            "intent": str(payload.get("intent", "") or "general"),
            "mode": str(payload.get("mode_used", "") or payload.get("mode", "") or "query"),
            "retrieval_sources": list((payload.get("retrieval_policy", {}) or {}).get("sources", []) or []),
            "expected_action": action,
            "expected_command": first_step.get("command", ""),
            "status": "adopted" if matched_tool else "missed",
            "matched_tool": matched_tool,
            "followup_tools": [
                str((_event_payload(item).get("tool_name") or _event_payload(item).get("name") or "") or "")
                for item in followups
            ],
        })

    total = len(records)
    adopted = sum(1 for record in records if record.get("status") == "adopted")
    missed = total - adopted
    adoption_rate = round(adopted / total, 3) if total else 0.0
    builder = EvalResultBuilder()
    if total == 0:
        builder.add("low", "no_agent_guidance_events", "近期没有记录 agent_guidance 事件，无法评估建议是否被执行。", 10)
    elif missed > 0:
        builder.add("medium", "agent_guidance_not_adopted", f"{missed} 条 agent guidance 没有匹配到后续执行工具。", min(40, missed * 15))
    if total >= 3 and adoption_rate < 0.6:
        builder.add("medium", "low_agent_guidance_adoption_rate", f"agent guidance adoption rate 仅 {adoption_rate}。", 20)

    return builder.finalize(
        workspace=config.workspace,
        session_id=session_id,
        summary={
            "total_guidance_events": total,
            "adopted_count": adopted,
            "missed_count": missed,
            "adoption_rate": adoption_rate,
        },
        adoption_records=records[:50],
    )


def memory_eval_agent_guidance_adoption_trend(
    workspace_file: str | Path,
    *,
    session_id: str = "",
    limit: int = 200,
) -> dict[str, Any]:
    """Run agent guidance adoption eval and append one trend point."""

    from ..benchmark.trending import record_agent_guidance_adoption_trend

    result = memory_eval_agent_guidance_adoption(workspace_file, session_id=session_id, limit=limit)
    summary = result.get("summary", {}) or {}
    missed_action_counts: dict[str, int] = {}
    for record in result.get("adoption_records", []) or []:
        if not isinstance(record, dict) or record.get("status") != "missed":
            continue
        action = str(record.get("expected_action", "") or "")
        if not action:
            continue
        missed_action_counts[action] = missed_action_counts.get(action, 0) + 1
    recorded = record_agent_guidance_adoption_trend(
        workspace_file,
        total_guidance_events=int(summary.get("total_guidance_events", 0) or 0),
        adopted_count=int(summary.get("adopted_count", 0) or 0),
        missed_count=int(summary.get("missed_count", 0) or 0),
        adoption_rate=float(summary.get("adoption_rate", 0.0) or 0.0),
        score=int(result.get("score", 0) or 0),
        quality=str(result.get("quality", "") or ""),
        session_id=session_id,
        missed_action_counts=missed_action_counts,
    )
    return {
        **recorded,
        "eval": result,
    }


def memory_eval_agent_guidance_replay(
    workspace_file: str | Path,
    *,
    session_id: str = "",
    limit: int = 200,
) -> dict[str, Any]:
    """Replay recorded agent guidance and classify why each recommendation did or did not land."""

    config, store = load_context(workspace_file)
    events = store.read_jsonl_prefer_backend(SESSION_EVENTS_FILE, limit=max(limit, 1))
    if session_id:
        events = [event for event in events if event.get("session_id") == session_id]

    records: list[dict[str, Any]] = []
    reason_counts: dict[str, int] = {}
    status_counts = {
        "adopted": 0,
        "missed": 0,
        "bypassed": 0,
        "unobservable": 0,
    }

    for index, event in enumerate(events):
        if event.get("event_type") not in {"agent_guidance", "agent_next_steps"}:
            continue
        payload = _event_payload(event)
        steps = payload.get("agent_next_steps", [])
        if not isinstance(steps, list) or not steps:
            continue
        first_step = next((step for step in steps if isinstance(step, dict) and step.get("action")), None)
        if not first_step:
            continue
        sid = str(event.get("session_id", "") or "")
        action = str(first_step.get("action", "") or "")
        followups = _agent_guidance_followups(events, index, sid)
        status, reason, matched = _classify_agent_guidance_replay(action, first_step, followups)
        status_counts[status] = status_counts.get(status, 0) + 1
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        records.append({
            "session_id": sid,
            "query": payload.get("query", "") or payload.get("intent", ""),
            "intent": str(payload.get("intent", "") or "general"),
            "mode": str(payload.get("mode_used", "") or payload.get("mode", "") or "query"),
            "retrieval_sources": list((payload.get("retrieval_policy", {}) or {}).get("sources", []) or []),
            "expected_action": action,
            "expected_command": first_step.get("command", ""),
            "status": status,
            "reason": reason,
            "matched_tool": matched,
            "followup_tools": [
                str((_event_payload(item).get("tool_name") or _event_payload(item).get("name") or "") or "")
                for item in followups[:8]
            ],
            "diagnostics": _agent_guidance_replay_diagnostics(first_step, followups),
        })

    total = len(records)
    adopted = status_counts.get("adopted", 0)
    bypassed = status_counts.get("bypassed", 0)
    unobservable = status_counts.get("unobservable", 0)
    missed = status_counts.get("missed", 0)
    adoption_rate = round(adopted / total, 3) if total else 0.0
    bypass_rate = round(bypassed / total, 3) if total else 0.0
    unobservable_rate = round(unobservable / total, 3) if total else 0.0

    builder = EvalResultBuilder()
    if total == 0:
        builder.add("low", "no_agent_guidance_events", "近期没有记录 agent_guidance 事件，无法回放建议执行链路。", 10)
    if bypassed > 0:
        builder.add("medium", "agent_guidance_bypassed", f"{bypassed} 条建议后续被本地搜索或非 Memory Center 工具绕过。", min(35, bypassed * 15))
    if missed > 0:
        builder.add("medium", "agent_guidance_missed", f"{missed} 条建议有后续工具调用但没有匹配预期动作。", min(35, missed * 12))
    if total >= 3 and unobservable_rate > 0.3:
        builder.add("medium", "agent_guidance_unobservable", f"agent guidance unobservable rate 为 {unobservable_rate}。", 20)
    if total >= 3 and adoption_rate < 0.6:
        builder.add("medium", "low_agent_guidance_replay_adoption_rate", f"agent guidance replay adoption rate 仅 {adoption_rate}。", 20)

    return builder.finalize(
        workspace=config.workspace,
        session_id=session_id,
        summary={
            "total_guidance_events": total,
            "adopted_count": adopted,
            "missed_count": missed,
            "bypassed_count": bypassed,
            "unobservable_count": unobservable,
            "adoption_rate": adoption_rate,
            "bypass_rate": bypass_rate,
            "unobservable_rate": unobservable_rate,
            "status_counts": status_counts,
            "reason_counts": reason_counts,
        },
        replay_records=records[:50],
    )


def memory_eval_agent_guidance_replay_campaign(
    workspace_file: str | Path,
    *,
    min_events: int = 20,
    required_intents: tuple[str, ...] = ("walkthrough", "impact", "mq", "config", "general"),
    limit: int = 500,
) -> dict[str, Any]:
    """Evaluate whether a real replay set is large and diverse enough for policy review.

    This gate is intentionally read-only: replay adoption is not evidence that a
    retrieval result was correct, so it never changes learned source weights.
    """
    replay = memory_eval_agent_guidance_replay(workspace_file, limit=limit)
    records = replay.get("replay_records", []) or []
    observed = {str(item.get("intent", "") or "general") for item in records if isinstance(item, dict)}
    expected = tuple(dict.fromkeys(item.strip().lower() for item in required_intents if item.strip()))
    missing = [item for item in expected if item not in observed]
    total = int((replay.get("summary", {}) or {}).get("total_guidance_events", 0) or 0)
    return {
        "schema_version": 1,
        "suite": "agent_guidance_replay_campaign",
        "replay": replay,
        "coverage": {"required_intents": list(expected), "observed_intents": sorted(observed), "missing_intents": missing},
        "thresholds": {"min_events": max(1, min_events)},
        "passed": total >= max(1, min_events) and not missing,
        "next_action": "Collect session_id-backed real tasks for each missing intent, then record human-verified retrieval outcomes separately before changing source weights.",
    }


def memory_eval_agent_guidance_replay_trend(
    workspace_file: str | Path,
    *,
    session_id: str = "",
    limit: int = 200,
) -> dict[str, Any]:
    """Run agent guidance replay eval and append one trend point."""

    from ..benchmark.trending import record_agent_guidance_replay_trend

    result = memory_eval_agent_guidance_replay(workspace_file, session_id=session_id, limit=limit)
    summary = result.get("summary", {}) or {}
    recorded = record_agent_guidance_replay_trend(
        workspace_file,
        total_guidance_events=int(summary.get("total_guidance_events", 0) or 0),
        adopted_count=int(summary.get("adopted_count", 0) or 0),
        missed_count=int(summary.get("missed_count", 0) or 0),
        bypassed_count=int(summary.get("bypassed_count", 0) or 0),
        unobservable_count=int(summary.get("unobservable_count", 0) or 0),
        adoption_rate=float(summary.get("adoption_rate", 0.0) or 0.0),
        bypass_rate=float(summary.get("bypass_rate", 0.0) or 0.0),
        unobservable_rate=float(summary.get("unobservable_rate", 0.0) or 0.0),
        score=int(result.get("score", 0) or 0),
        quality=str(result.get("quality", "") or ""),
        session_id=session_id,
        reason_counts={
            str(reason): int(count or 0)
            for reason, count in (summary.get("reason_counts", {}) or {}).items()
            if str(reason)
        },
    )
    return {
        **recorded,
        "eval": result,
    }


def _match_agent_guidance_followup(action: str, followups: list[dict[str, Any]]) -> str:
    for event in followups:
        payload = _event_payload(event)
        tool_name = str(payload.get("tool_name") or payload.get("name") or "")
        mode = str(payload.get("mode") or "")
        if _tool_matches_agent_guidance_action(action, tool_name, mode, payload):
            return tool_name or mode
    return ""


def _agent_guidance_followups(events: list[dict[str, Any]], index: int, session_id: str) -> list[dict[str, Any]]:
    if not session_id:
        return []
    followups: list[dict[str, Any]] = []
    for candidate in events[index + 1:]:
        if candidate.get("session_id") != session_id:
            continue
        event_type = candidate.get("event_type")
        if event_type in {"agent_guidance", "agent_next_steps", "session_end"}:
            break
        if event_type == "tool_call":
            followups.append(candidate)
        if len(followups) >= 8:
            break
    return followups


def _classify_agent_guidance_replay(
    action: str,
    step: dict[str, Any],
    followups: list[dict[str, Any]],
) -> tuple[str, str, str]:
    if not followups:
        return "unobservable", "no_followup_tool_call", ""
    for event in followups:
        if _is_local_search_or_bypass_tool(event):
            return "bypassed", "local_search_or_non_memory_tool_used", _tool_name_from_event(event)
        payload = _event_payload(event)
        tool_name = str(payload.get("tool_name") or payload.get("name") or "")
        mode = str(payload.get("mode") or "")
        if _tool_matches_agent_guidance_action(action, tool_name, mode, payload):
            return "adopted", "matched_expected_tool", tool_name or mode
    if not _step_has_execution_hint(step):
        return "missed", "guidance_missing_executable_command", ""
    if _step_missing_target_hint(step):
        return "missed", "guidance_missing_target_hint", ""
    return "missed", "memory_tool_used_but_action_mismatch", ""


def _agent_guidance_replay_diagnostics(step: dict[str, Any], followups: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "has_command": bool(str(step.get("command", "") or "").strip()),
        "has_read_targets": bool(step.get("read_targets") or step.get("target") or step.get("target_ref")),
        "followup_count": len(followups),
        "first_followup_tool": _tool_name_from_event(followups[0]) if followups else "",
    }


def _tool_name_from_event(event: dict[str, Any]) -> str:
    payload = _event_payload(event)
    return str((payload.get("tool_name") or payload.get("name") or payload.get("mode") or "") or "")


def _is_local_search_or_bypass_tool(event: dict[str, Any]) -> bool:
    payload = _event_payload(event)
    tool_name = _tool_name_from_event(event).lower()
    if tool_name.startswith(("memory_", "workspace_", "mc_")) or "mc_lookup" in tool_name:
        return False
    local_tools = {"rg", "grep", "find", "sed", "cat", "ls", "read_file", "open"}
    if tool_name in local_tools:
        return True
    if tool_name not in {"exec_command", "shell", "terminal", "bash", "zsh"}:
        return False
    for field in ("cmd", "command", "script"):
        command = payload.get(field)
        if not isinstance(command, str) or not command.strip():
            continue
        try:
            executable = shlex.split(command, posix=True)[0]
        except ValueError:
            continue
        if executable.rsplit("/", 1)[-1].lower() in local_tools:
            return True
    return False


def _step_has_execution_hint(step: dict[str, Any]) -> bool:
    command = str(step.get("command", "") or "").strip()
    mode = str(step.get("mode", "") or "").strip()
    return bool(command or mode)


def _step_missing_target_hint(step: dict[str, Any]) -> bool:
    action = str(step.get("action", "") or "")
    if action in {"use_read_targets", "inspect_top_result", "refresh_or_read_live_files", "validate_semantic_hit"}:
        return not bool(step.get("read_targets") or step.get("target") or step.get("target_ref") or step.get("result_ref"))
    return False


def _tool_matches_agent_guidance_action(action: str, tool_name: str, mode: str, payload: dict[str, Any]) -> bool:
    normalized_tool = tool_name.lower()
    normalized_mode = mode.lower()
    payload_text = json.dumps(payload, ensure_ascii=False).lower()
    if action == "switch_to_walkthrough":
        return "walkthrough" in normalized_tool or normalized_mode == "walkthrough" or "mode=\"walkthrough\"" in payload_text
    if action in {"inspect_top_result", "validate_semantic_hit", "refresh_or_read_live_files", "use_read_targets"}:
        return any(token in normalized_tool for token in ["read", "open", "memory_ref", "workspace_trace", "memory_context", "memory_search_code"])
    if action == "refine_query":
        return any(token in normalized_tool for token in ["memory_query_hybrid", "mc_lookup", "memory_symbol", "memory_search_code"])
    return normalized_tool.startswith("memory_") or normalized_tool.startswith("workspace_")


def memory_eval_index_freshness(
    workspace_file: str | Path,
    scope: str = "all",
) -> dict[str, Any]:
    from .impact import memory_detect_changes  # lazy import

    config, store = load_context(workspace_file)
    builder = EvalResultBuilder()
    changed = memory_detect_changes(workspace_file, scope=scope)
    changed_files = changed.get("changed_files", []) or []
    semantic = semantic_index_stats(workspace_file)
    index_files = [
        store.index_dir / "file-index.json",
        store.index_dir / "java-symbol-index.json",
        store.index_dir / "api-index.json",
        store.index_dir / "feign-index.json",
        store.index_dir / "mq-index.json",
        store.index_dir / "config-index.json",
        store.index_dir / "service-topology.json",
        store.index_dir / "semantic-node-index.json",
        store.graph_dir / "graph.db",
    ]
    existing = [path for path in index_files if path.exists()]
    latest_index_mtime = max((path.stat().st_mtime for path in existing), default=0.0)
    stale_changed_files = []
    for rel in changed_files[:200]:
        matched = next((row for row in store.read_json_prefer_backend("file-index.json", []) if row.get("path") == rel), None)
        abs_path = Path(matched.get("abs_path", "")) if matched and matched.get("abs_path") else None
        if abs_path and abs_path.exists() and abs_path.stat().st_mtime > latest_index_mtime:
            stale_changed_files.append(rel)
    if changed_files and stale_changed_files:
        builder.add("high", "stale_index_after_changes", "存在变更文件比当前索引更新，建议执行增量或全量 reindex。", 35)
    if not semantic.get("ready"):
        builder.add("medium", "semantic_not_ready", "语义索引未就绪，query/context/impact 的召回质量会下降。", 20)
    if not existing:
        builder.add("high", "missing_index_files", "未发现任何索引文件，workspace 处于未初始化索引状态。", 100)
    return builder.finalize(
        workspace=config.workspace,
        scope=scope,
        changed_file_count=len(changed_files),
        stale_changed_files=stale_changed_files[:20],
        semantic_index=semantic,
        latest_index_mtime=latest_index_mtime,
    )


def memory_eval_tool_adoption(
    workspace_file: str | Path,
    limit: int = 200,
) -> dict[str, Any]:
    from .query import memory_tool_usage_report  # lazy import

    config, _ = load_context(workspace_file)
    report = memory_tool_usage_report(workspace_file, limit=limit)
    summary = report.get("summary", {}) or {}
    builder = EvalResultBuilder()
    if float(summary.get("memory_center_ratio", 0.0)) < 0.25 and int(summary.get("total_tool_calls", 0)) > 0:
        builder.add("medium", "low_memory_center_ratio", "近期工具调用中 Memory Center 占比较低，模型可能仍主要依赖本地搜索。", 25)
    if int(summary.get("lookup_tool_total", 0)) == 0 and int(summary.get("total_tool_calls", 0)) > 0:
        builder.add("medium", "no_lookup_tool_usage", "近期没有使用 Memory Center lookup 工具，类/符号检索可能未按协议走。", 20)
    if int(summary.get("suspected_bypass_count", 0)) > 0:
        builder.add("high", "suspected_bypass_detected", "检测到疑似绕过 Memory Center 的检索行为。", min(40, int(summary.get("suspected_bypass_count", 0)) * 10))
    return builder.finalize(
        workspace=config.workspace,
        usage_report=report,
        total_tool_calls=summary.get("total_tool_calls", 0),
        memory_center_ratio=summary.get("memory_center_ratio", 0.0),
    )


def memory_eval_workflow_orchestration(
    workspace_file: str | Path,
    task_id: str = "",
    session_id: str = "",
    intent: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    from memory_center.core.assessment.evals import eval_workflow_orchestration

    from .session import workspace_recent_evidence

    config, store = load_context(workspace_file)
    evidence = workspace_recent_evidence(workspace_file, task_id=task_id, session_id=session_id, limit=limit, budget="large")
    events = evidence.get("evidence", [])
    return eval_workflow_orchestration(events, intent=intent)


def memory_eval_context_weight(
    workspace_file: str | Path,
    intent: str = "",
    limit: int = 8,
) -> dict[str, Any]:
    from .resume import workspace_resume_packet  # lazy import
    from .workspace_ops import workspace_dashboard, workspace_sniff  # lazy import

    config, _ = load_context(workspace_file)
    sniff_small = workspace_sniff(workspace_file, intent or "context weight", limit=limit, view="compact", budget="small")
    sniff_large = workspace_sniff(workspace_file, intent or "context weight", limit=limit, view="compact", budget="large")
    resume_small = workspace_resume_packet(workspace_file, intent=intent, limit=limit, view="compact", budget="small")
    dashboard_small = workspace_dashboard(workspace_file, intent=intent, limit=limit, view="compact", budget="small")
    builder = EvalResultBuilder()
    sniff_small_chars = len(json.dumps(sniff_small, ensure_ascii=False))
    sniff_large_chars = len(json.dumps(sniff_large, ensure_ascii=False))
    resume_small_chars = len(json.dumps(resume_small, ensure_ascii=False))
    dashboard_small_chars = len(json.dumps(dashboard_small, ensure_ascii=False))
    sniff_small_tokens = estimate_tokens(json.dumps(sniff_small, ensure_ascii=False))
    sniff_large_tokens = estimate_tokens(json.dumps(sniff_large, ensure_ascii=False))
    resume_small_tokens = estimate_tokens(json.dumps(resume_small, ensure_ascii=False))
    dashboard_small_tokens = estimate_tokens(json.dumps(dashboard_small, ensure_ascii=False))
    # Also get full-view token counts for savings comparison
    sniff_full = workspace_sniff(workspace_file, intent or "context weight", limit=limit, view="full", budget="large")
    sniff_full_tokens = estimate_tokens(json.dumps(sniff_full, ensure_ascii=False))
    sniff_savings_pct = round((1 - sniff_small_tokens / (sniff_full_tokens or 1)) * 100, 1)
    resume_full = workspace_resume_packet(workspace_file, intent=intent, limit=limit, view="full", budget="medium")
    resume_full_tokens = estimate_tokens(json.dumps(resume_full, ensure_ascii=False))
    resume_savings_pct = round((1 - resume_small_tokens / (resume_full_tokens or 1)) * 100, 1)
    dashboard_full = workspace_dashboard(workspace_file, intent=intent, limit=limit, view="full", budget="medium")
    dashboard_full_tokens = estimate_tokens(json.dumps(dashboard_full, ensure_ascii=False))
    dashboard_savings_pct = round((1 - dashboard_small_tokens / (dashboard_full_tokens or 1)) * 100, 1)
    if sniff_small_chars > 4500:
        builder.add("medium", "sniff_small_too_heavy", "sniff 在 small budget 下仍偏重，建议继续压缩字段或条目数。", 20)
    if resume_small_chars > 2800:
        builder.add("medium", "resume_small_too_heavy", "resume packet 在 small budget 下仍偏重。", 15)
    if dashboard_small_chars > 5200:
        builder.add("medium", "dashboard_small_too_heavy", "workspace dashboard 在 small budget 下仍偏重。", 20)
    if sniff_large_chars <= sniff_small_chars:
        builder.add("low", "budget_not_effective", "budget small/large 的输出规模没有明显拉开。", 10)
    if sniff_savings_pct < 40:
        builder.add("low", "sniff_savings_low", f"sniff compact 只省了 {sniff_savings_pct}% token，压缩效果不足。", 10)
    if resume_savings_pct < 40:
        builder.add("low", "resume_savings_low", f"resume compact 只省了 {resume_savings_pct}% token，压缩效果不足。", 10)
    return builder.finalize(
        workspace=config.workspace,
        intent=intent,
        sniff_small_chars=sniff_small_chars,
        sniff_large_chars=sniff_large_chars,
        resume_small_chars=resume_small_chars,
        dashboard_small_chars=dashboard_small_chars,
        sniff_small_tokens=sniff_small_tokens,
        sniff_large_tokens=sniff_large_tokens,
        sniff_full_tokens=sniff_full_tokens,
        sniff_savings_pct=sniff_savings_pct,
        resume_small_tokens=resume_small_tokens,
        resume_full_tokens=resume_full_tokens,
        resume_savings_pct=resume_savings_pct,
        dashboard_small_tokens=dashboard_small_tokens,
        dashboard_full_tokens=dashboard_full_tokens,
        dashboard_savings_pct=dashboard_savings_pct,
    )


def memory_eval_token_gain(
    workspace_file: str | Path,
    *,
    tool_name: str = "",
    budget: str = "",
    model: str = "",
    limit: int = 200,
) -> dict[str, Any]:
    """Evaluate token savings from compact operations, similar to rtk's gain command."""
    from memory_center.core.observability.tracking import query_token_gain

    config, _ = load_context(workspace_file)
    gain_report = query_token_gain(
        workspace_file,
        tool_name=tool_name,
        budget=budget,
        model=model,
        limit=limit,
    )
    builder = EvalResultBuilder()
    overall_pct = gain_report.get("overall_savings_pct", 0)
    if overall_pct < 30 and gain_report.get("total_records", 0) > 5:
        builder.add("medium", "low_overall_savings", f"整体 compact savings 仅 {overall_pct}%，压缩效果不足。", 20)
    if gain_report.get("total_records", 0) == 0:
        builder.add("low", "no_gain_records", "尚未有任何 compact gain 记录，compact 视图可能未被调用。", 10)
    bottom = gain_report.get("bottom_5_savings", [])
    for entry in bottom[:3]:
        if entry.get("avg_savings_pct", 100) < 30:
            builder.add("low", f"low_savings_{entry.get('tool', '')}", f"{entry.get('tool')} compact 平均省 {entry.get('avg_savings_pct')}% token。", 10)
    return builder.finalize(
        workspace=config.workspace,
        overall_savings_pct=overall_pct,
        total_records=gain_report.get("total_records", 0),
        total_saved_tokens=gain_report.get("total_saved_tokens", 0),
        per_tool_stats=gain_report.get("per_tool_stats", {}),
        top_5_savings=gain_report.get("top_5_savings", []),
        bottom_5_savings=gain_report.get("bottom_5_savings", []),
    )


def memory_eval_token_benchmark(
    workspace_file: str | Path,
    intent: str = "",
    limit: int = 8,
) -> dict[str, Any]:
    """Run all 7 high-frequency returns at small/medium/large budgets and report token counts.

    Follows agentmemory's benchmark pattern: measure actual token impact per function per budget.
    Returns a comparison table suitable for regression testing.
    """
    from .resume import workspace_handoff_packet, workspace_resume_packet
    from .session import workspace_recent_evidence
    from .workspace_ops import workspace_continuity_dashboard, workspace_dashboard, workspace_sniff, workspace_status

    config, _ = load_context(workspace_file)
    budget_tiers = ["tiny", "small", "medium", "large"]
    functions = {
        "sniff": lambda b: workspace_sniff(workspace_file, intent or "benchmark", limit=limit, view="compact", budget=b),
        "status": lambda b: workspace_status(workspace_file, view="compact", budget=b),
        "resume": lambda b: workspace_resume_packet(workspace_file, intent=intent, limit=limit, view="compact", budget=b),
        "recent_evidence": lambda b: workspace_recent_evidence(workspace_file, limit=limit, budget=b, view="compact"),
        "continuity": lambda b: workspace_continuity_dashboard(workspace_file, intent=intent, limit=limit, view="compact", budget=b),
        "dashboard": lambda b: workspace_dashboard(workspace_file, intent=intent, limit=limit, view="compact", budget=b),
        "handoff": lambda b: workspace_handoff_packet(workspace_file, target_model="codex", intent=intent or "benchmark", limit=limit, view="compact", budget=b),
    }
    results = {}
    for name, fn in functions.items():
        row = {}
        for budget in budget_tiers:
            payload = fn(budget)
            text = json.dumps(payload, ensure_ascii=False)
            tokens = estimate_tokens(text)
            row[budget] = {"tokens": tokens, "chars": len(text)}
        small_t = row["small"]["tokens"]
        large_t = row["large"]["tokens"]
        savings_pct = round((1 - small_t / (large_t or 1)) * 100, 1)
        row["savings_pct"] = savings_pct
        results[name] = row

    total_tiny = sum(results[n].get("tiny", {}).get("tokens", 0) for n in results)
    total_small = sum(results[n]["small"]["tokens"] for n in results)
    total_medium = sum(results[n]["medium"]["tokens"] for n in results)
    total_large = sum(results[n]["large"]["tokens"] for n in results)

    builder = EvalResultBuilder()
    if total_small > 8000:
        builder.add("medium", "total_small_heavy", f"small budget 总计 {total_small} tokens，建议进一步压缩。", 20)
    for name, row in results.items():
        if row["savings_pct"] < 30:
            builder.add("low", f"{name}_low_savings", f"{name} compact 只省了 {row['savings_pct']}%。", 5)

    return builder.finalize(
        workspace=config.workspace,
        intent=intent,
        benchmark=results,
        totals={"tiny": total_tiny, "small": total_small, "medium": total_medium, "large": total_large},
    )


def memory_eval_parser_benchmark(
    workspace_file: str | Path,
    *,
    limit: int = 200,
    max_findings: int = 20,
) -> dict[str, Any]:
    """Run a real-workspace comparison between regex and tree-sitter Java parsers."""
    from ..indexing.benchmark import benchmark_java_parsers

    return benchmark_java_parsers(
        workspace_file,
        limit=limit,
        max_findings=max_findings,
    )


def memory_eval_java_call_resolution(
    workspace_file: str | Path,
    cases_file: str | Path,
    *,
    min_recall: float = 0.90,
    min_confidence_rate: float = 0.85,
    max_unresolved_rate: float = 0.10,
    fail_on_unexpected_high_confidence: bool = False,
    fail_on_forbidden_high_confidence: bool = False,
) -> dict[str, Any]:
    """Evaluate indexed Java CALLS_METHOD precision against logical cases."""
    from ..benchmark.java_call_resolution import run_java_call_resolution_suite

    return run_java_call_resolution_suite(
        workspace_file,
        cases_file,
        min_recall=min_recall,
        min_confidence_rate=min_confidence_rate,
        max_unresolved_rate=max_unresolved_rate,
        fail_on_unexpected_high_confidence=fail_on_unexpected_high_confidence,
        fail_on_forbidden_high_confidence=fail_on_forbidden_high_confidence,
    )


def memory_eval_java_call_resolution_review(
    workspace_file: str | Path,
    cases_file: str | Path,
    *,
    limit: int = 200,
) -> dict[str, Any]:
    """Return deduplicated, unclassified high-confidence Java call edges."""
    from ..benchmark.java_call_resolution import review_java_call_resolution_suite

    return review_java_call_resolution_suite(workspace_file, cases_file, limit=limit)


def memory_eval_java_call_resolution_unresolved(
    workspace_file: str | Path,
    *,
    limit: int = 30,
) -> dict[str, Any]:
    """Summarize unresolved Java call categories for evidence-led resolver work."""
    from ..benchmark.java_call_resolution import summarize_unresolved_java_calls

    return summarize_unresolved_java_calls(workspace_file, sample_limit=limit)


def _benchmark_baseline_path(workspace_file: str | Path) -> Path:
    _, store = load_context(workspace_file)
    return store.base_dir / "benchmark-baseline.json"


def _extract_benchmark_baseline(benchmark_result: dict[str, Any]) -> dict[str, Any]:
    """Extract a storable baseline snapshot from a benchmark result."""
    from datetime import datetime, timezone
    functions = {}
    for name, row in benchmark_result.get("benchmark", {}).items():
        functions[name] = {
            budget: {"tokens": row[budget]["tokens"], "chars": row[budget]["chars"]}
            for budget in ("small", "medium", "large")
        }
        functions[name]["savings_pct"] = row.get("savings_pct", 0.0)
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "totals": benchmark_result.get("totals", {}),
        "functions": functions,
    }


def memory_eval_token_benchmark_save(
    workspace_file: str | Path,
    intent: str = "",
    limit: int = 8,
) -> dict[str, Any]:
    """Run token benchmark and save the result as a regression baseline."""
    result = memory_eval_token_benchmark(workspace_file, intent=intent, limit=limit)
    baseline = _extract_benchmark_baseline(result)
    path = _benchmark_baseline_path(workspace_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8")

    # Record trend points for time-series analysis
    from ..benchmark.trending import record_benchmark_trend
    for fn_name, fn_data in result.get("benchmark", {}).items():
        for budget in ("small", "medium", "large"):
            budget_data = fn_data.get(budget, {})
            raw = budget_data.get("tokens", 0)
            compact = budget_data.get("tokens", 0)  # baseline = raw for save
            record_benchmark_trend(
                workspace_file, fn_name, raw, compact,
                budget=budget, view="compact",
            )

    return {"saved": True, "path": str(path), "baseline": baseline}


def memory_eval_token_benchmark_compare(
    workspace_file: str | Path,
    intent: str = "",
    limit: int = 8,
    regression_threshold: int = 15,
) -> dict[str, Any]:
    """Run token benchmark and compare against the stored baseline.

    Returns the benchmark result augmented with regression analysis.
    If any function regresses by more than regression_threshold%, a high-severity finding is added.
    """
    path = _benchmark_baseline_path(workspace_file)
    if not path.exists():
        result = memory_eval_token_benchmark(workspace_file, intent=intent, limit=limit)
        result["regression"] = []
        result["baseline_path"] = str(path)
        result["baseline_status"] = "no_baseline"
        return result

    baseline = json.loads(path.read_text(encoding="utf-8"))
    result = memory_eval_token_benchmark(workspace_file, intent=intent, limit=limit)
    current_functions = result.get("benchmark", {})
    baseline_functions = baseline.get("functions", {})
    baseline_totals = baseline.get("totals", {})

    regressions = []
    builder = EvalResultBuilder()

    for name, current_row in current_functions.items():
        base_row = baseline_functions.get(name)
        if not base_row:
            continue
        for budget in ("small", "medium", "large"):
            current_tokens = current_row.get(budget, {}).get("tokens", 0)
            base_tokens = base_row.get(budget, {}).get("tokens", 0)
            if base_tokens <= 0:
                continue
            delta_pct = round((current_tokens - base_tokens) / base_tokens * 100, 1)
            if delta_pct > regression_threshold:
                regressions.append({
                    "function": name,
                    "budget": budget,
                    "baseline_tokens": base_tokens,
                    "current_tokens": current_tokens,
                    "delta_pct": delta_pct,
                })

    for reg in regressions:
        builder.add(
            "high",
            f"regression_{reg['function']}_{reg['budget']}",
            f"{reg['function']}({reg['budget']}) 回归 {reg['delta_pct']}%：{reg['baseline_tokens']}→{reg['current_tokens']} tokens",
            40,
        )

    current_totals = result.get("totals", {})
    base_small = baseline_totals.get("small", 0)
    if base_small > 0:
        total_delta_pct = round((current_totals.get("small", 0) - base_small) / base_small * 100, 1)
        if total_delta_pct > 20:
            builder.add(
                "medium",
                "total_small_regression",
                f"small budget 总量回归 {total_delta_pct}%：{base_small}→{current_totals.get('small', 0)} tokens",
                25,
            )

    eval_result = builder.finalize(
        workspace=result.get("workspace", ""),
        intent=intent,
        benchmark=result.get("benchmark", {}),
        totals=current_totals,
        regressions=regressions,
        baseline_path=str(path),
        baseline_totals=baseline_totals,
        baseline_created_at=baseline.get("created_at", ""),
    )

    # Record trend points for time-series analysis
    from ..benchmark.trending import record_benchmark_trend
    for fn_name, fn_data in result.get("benchmark", {}).items():
        for budget in ("small", "medium", "large"):
            budget_data = fn_data.get(budget, {})
            raw = budget_data.get("tokens", 0)
            record_benchmark_trend(
                workspace_file, fn_name, raw, raw,
                budget=budget, view="compact",
            )

    return eval_result
