from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..artifacts import get_task_artifact, list_task_spaces
from ..rules import (
    DEFAULT_HANDOFF_PROFILES,
    ensure_default_rules,
)
from ..schemas import with_schema
from ..store import WorkspaceStore
from ..timeline import timeline_query
from ..tracking import log_token_gain
from .common import (
    LAYER_L0,
    LAYER_L1,
    LAYER_L2,
    LAYER_L3,
    SESSION_SUMMARIES_FILE,
    TOOL_WORKSPACE_LOG_SESSION_EVENT,
    TOOL_WORKSPACE_SYNC_CASE_ARTIFACTS,
    TOOL_WORKSPACE_SYNC_SNIFF_ARTIFACTS,
    _is_compact_view,
    _load_handoff_rules,
    _load_resume_rules,
    _normalize_model_name,
    _suggest_resume_context,
    load_context,
    tokenize,
)
from .compact import _compact_handoff_packet, _compact_resume_packet, _measure_compact_gain
from .query import memory_query
from .session import workspace_recent_evidence


def workspace_resume_packet(
    workspace_file: str | Path,
    task_id: str = "",
    session_id: str = "",
    intent: str = "",
    limit: int = 10,
    view: str = "compact",
    budget: str = "medium",
) -> dict[str, Any]:
    from .workspace import workspace_status  # lazy import to avoid circular dep

    config, store = load_context(workspace_file)
    resolved_task_id = task_id.strip()
    focus_task = workspace_status(workspace_file).get("current_focus_task")
    if not resolved_task_id and focus_task:
        resolved_task_id = str(focus_task.get("task_id", "") or "")
    task_meta = None
    current_summary = ""
    if resolved_task_id:
        tasks = list_task_spaces(workspace_file, include_archived=True)
        task_meta = next(
            (
                item
                for item in tasks.get("active_tasks", []) + tasks.get("archived_tasks", [])
                if item.get("task_id") == resolved_task_id
            ),
            None,
        )
        current_summary = get_task_artifact(workspace_file, resolved_task_id, "current_summary").get("content", "")
    resume_rules = _load_resume_rules(store, intent or current_summary)
    evidence = workspace_recent_evidence(
        workspace_file,
        task_id=resolved_task_id,
        session_id=session_id,
        limit=int(resume_rules.get("evidence_limit", limit)),
        budget=budget,
        view=view,
    ).get("evidence", [])
    next_actions = workspace_next_actions(
        workspace_file,
        task_id=resolved_task_id,
        session_id=session_id,
        intent=intent or current_summary,
        limit=int(resume_rules.get("action_limit", limit)),
    ).get("actions", [])
    unresolved = workspace_unresolved_items(
        workspace_file,
        task_id=resolved_task_id,
        session_id=session_id,
        intent=intent or current_summary,
        limit=int(resume_rules.get("unresolved_limit", limit)),
    ).get("items", [])
    from .write import workspace_replay_write_chain

    replay = workspace_replay_write_chain(workspace_file, task_id=resolved_task_id, session_id=session_id, limit=limit)
    packet = {
        "workspace": config.workspace,
        "task_id": resolved_task_id,
        "session_id": session_id,
        "task_title": (task_meta or {}).get("title", ""),
        "task_status": (task_meta or {}).get("status", ""),
        "current_summary": current_summary,
        "current_phase": _infer_task_phase(current_summary, replay.get("timeline", [])),
        "latest_receipts": replay.get("timeline", [])[-int(resume_rules.get("receipt_limit", 5)):],
        "recent_evidence": evidence,
        "next_recommended_actions": next_actions,
        "unresolved_items": unresolved,
        "verification_pending": bool(unresolved),
        "resume_rule_profile": resume_rules.get("profile_name", "default"),
    }
    fields = resume_rules.get("fields", list(packet.keys()))
    filtered = {"workspace": config.workspace}
    for key in fields:
        if key in packet:
            filtered[key] = packet[key]
    filtered["resume_rule_profile"] = packet.get("resume_rule_profile", "default")
    result = with_schema("resume_packet", filtered)
    if (view or "").strip().lower() == "compact":
        compact = _compact_resume_packet(result, budget=budget)
        gain = _measure_compact_gain(result, compact)
        log_token_gain(workspace_file, "workspace_resume_packet", budget=budget, model="", raw_tokens=gain["raw_tokens"], compact_tokens=gain["compact_tokens"], view=view)
        return compact
    return result


def workspace_resume_context(workspace_file: str | Path, intent: str, limit: int = 5) -> dict[str, Any]:
    config, store = load_context(workspace_file)
    query_result = memory_query(workspace_file, intent, limit=limit)
    summaries = store.read_jsonl_prefer_backend(SESSION_SUMMARIES_FILE, limit=500)
    tokens = tokenize(intent)
    related_sessions = []
    for item in summaries:
        haystack = json.dumps(item, ensure_ascii=False).lower()
        score = sum(1 for token in tokens if token in haystack)
        if score > 0:
            related_sessions.append({**item, "match_score": score})
    related_sessions.sort(key=lambda item: (-int(item.get("match_score", 0)), item.get("created_at", "")))
    related_cases = [
        item
        for item in store.read_jsonl_prefer_backend("cross-service-task-memory.jsonl", limit=300)
        if any(token in json.dumps(item, ensure_ascii=False).lower() for token in tokens)
    ][-limit:]
    return {
        "workspace": config.workspace,
        "intent": intent,
        "retrieval_summary": query_result.get("retrieval_summary", {}),
        "related_sessions": related_sessions[:limit],
        "related_cases": related_cases,
        "entrypoints": query_result.get("matches", [])[:limit],
        "suggested_context": _suggest_resume_context(
            intent,
            related_sessions[:limit],
            related_cases,
            query_result.get("matches", [])[:limit],
        ),
    }


def workspace_unresolved_items(
    workspace_file: str | Path,
    task_id: str = "",
    session_id: str = "",
    intent: str = "",
    limit: int = 10,
) -> dict[str, Any]:
    from .eval import memory_eval_write_quality

    config, _ = load_context(workspace_file)
    unresolved: list[str] = []
    quality = memory_eval_write_quality(
        workspace_file, task_id=task_id, session_id=session_id, intent=intent, limit=max(limit, 20)
    )
    for finding in quality.get("findings", []):
        unresolved.append(str(finding.get("message", "") or "").strip())
    if task_id.strip():
        current_summary = get_task_artifact(workspace_file, task_id.strip(), "current_summary").get("content", "")
        if "Verification pending" in current_summary or "verification_pending" in current_summary.lower():
            unresolved.append("任务摘要显示仍有待验证项。")
    seen = set()
    unique = []
    for item in unresolved:
        if item and item not in seen:
            seen.add(item)
            unique.append(item)
    return {
        "workspace": config.workspace,
        "task_id": task_id,
        "session_id": session_id,
        "items": unique[:limit],
    }


def workspace_next_actions(
    workspace_file: str | Path,
    task_id: str = "",
    session_id: str = "",
    intent: str = "",
    limit: int = 8,
) -> dict[str, Any]:
    from .eval import memory_eval_write_quality

    config, _ = load_context(workspace_file)
    actions: list[str] = []
    quality = memory_eval_write_quality(
        workspace_file, task_id=task_id, session_id=session_id, intent=intent, limit=max(limit, 20)
    )
    layer_set = set(quality.get("layers_present", []))
    if session_id.strip() and LAYER_L0 not in layer_set:
        actions.append("先补 `workspace_log_session_event`，把关键过程写入 L0 session memory。")
    if task_id.strip() and LAYER_L2 not in layer_set:
        actions.append("先补 `workspace_sync_sniff_artifacts` 或 `workspace_sync_case_artifacts`，把任务上下文写入 L2 task space。")
    if session_id.strip() and LAYER_L1 not in layer_set:
        actions.append("补 `workspace_record_case`，把当前会话沉淀为 L1 case memory。")
    if any(k in intent.lower() for k in ["规则", "规范", "migration", "invariant"]) and LAYER_L3 not in layer_set:
        actions.append("补 `memory_execute_write` 或 `workspace_artifact_update`，把规则类信息写入 L3 核心记忆块。")
    unresolved = workspace_unresolved_items(
        workspace_file, task_id=task_id, session_id=session_id, intent=intent, limit=limit
    ).get("items", [])
    if unresolved:
        actions.append(f"优先处理未解决项：{unresolved[0]}")
    if not actions:
        actions.append("继续沿当前任务推进，优先核对验证项与风险点是否已覆盖。")
    return {
        "workspace": config.workspace,
        "task_id": task_id,
        "session_id": session_id,
        "actions": actions[:limit],
    }


def workspace_handoff_packet(
    workspace_file: str | Path,
    target_model: str,
    task_id: str = "",
    session_id: str = "",
    intent: str = "",
    limit: int = 10,
    view: str = "compact",
    budget: str = "medium",
) -> dict[str, Any]:
    from .eval import memory_eval_write_quality

    config, store = load_context(workspace_file)
    profile = workspace_model_profile(target_model, workspace_file=workspace_file)
    handoff_rules = _load_handoff_rules(store, profile.get("normalized_model", ""))
    resume_packet = workspace_resume_packet(
        workspace_file, task_id=task_id, session_id=session_id, intent=intent, limit=limit, view=view, budget=budget
    )
    quality = memory_eval_write_quality(
        workspace_file,
        task_id=resume_packet.get("task_id", ""),
        session_id=session_id,
        intent=intent or resume_packet.get("current_summary", ""),
        limit=limit,
    )
    minimal_context = {
        key: resume_packet.get(key)
        for key in profile.get("preferred_payload", [])
        if key in resume_packet
    }
    notes = [
        f"交接风格：{profile.get('handoff_style', 'balanced')}",
        f"优先发挥：{'、'.join(profile.get('strengths', [])[:3])}",
    ]
    if quality.get("findings"):
        notes.append(f"当前记忆覆盖缺口：{quality['findings'][0].get('message', '')}")
    packet_body = {
        "what_has_been_done": resume_packet.get("latest_receipts", [])[-int(handoff_rules.get("done_limit", 5)):],
        "what_not_to_repeat": profile.get("avoid", []),
        "what_is_risky": quality.get("findings", [])[: int(handoff_rules.get("risk_limit", 5))],
        "what_to_check_next": resume_packet.get("next_recommended_actions", [])[: int(handoff_rules.get("next_limit", 5))],
        "minimal_required_context": minimal_context,
        "recent_evidence": resume_packet.get("recent_evidence", [])[: int(handoff_rules.get("evidence_limit", 5))],
        "notes": notes,
    }

    # Enrich with DrillDownNavigator context if session_id is available
    if session_id:
        try:
            from ..navigation.drilldown import DrillDownNavigator
            with DrillDownNavigator(workspace_file) as nav:
                drill_ctx = nav.build_handoff_context(session_id, include_refs=False)
                if drill_ctx.get("key_points"):
                    packet_body["key_points"] = drill_ctx["key_points"]
                if drill_ctx.get("open_questions"):
                    packet_body["open_questions"] = drill_ctx["open_questions"]
                if drill_ctx.get("next_steps"):
                    existing = packet_body.get("what_to_check_next", [])
                    for step in drill_ctx["next_steps"]:
                        if step not in existing:
                            existing.append(step)
                    packet_body["what_to_check_next"] = existing[: int(handoff_rules.get("next_limit", 5))]
        except Exception:
            pass  # DrillDown is optional enrichment, don't fail handoff
    packet = {
        "workspace": config.workspace,
        "target_model": target_model,
        "task_id": resume_packet.get("task_id", ""),
        "session_id": session_id,
        "model_profile": profile,
        "handoff_rule_profile": handoff_rules.get("profile_name", "default"),
        "handoff_packet": {
            k: v
            for k, v in packet_body.items()
            if k in handoff_rules.get("include_sections", list(packet_body.keys()))
        },
    }
    history_item = {
        "target_model": target_model,
        "normalized_model": profile.get("normalized_model", ""),
        "task_id": packet.get("task_id", ""),
        "session_id": session_id,
        "intent": intent,
        "current_phase": resume_packet.get("current_phase", ""),
        "quality": quality.get("quality", ""),
        "score": quality.get("score", 0),
    }
    store.append_jsonl("handoff-history.jsonl", history_item)
    packet["handoff_ref"] = "memory/handoff-history.jsonl"
    result = with_schema("handoff_packet", packet)
    if _is_compact_view(view):
        compact = _compact_handoff_packet(result, budget=budget)
        gain = _measure_compact_gain(result, compact)
        log_token_gain(workspace_file, "workspace_handoff_packet", budget=budget, model=target_model, raw_tokens=gain["raw_tokens"], compact_tokens=gain["compact_tokens"], view=view)
        return compact
    return result


def workspace_handoff_history(
    workspace_file: str | Path,
    target_model: str = "",
    task_id: str = "",
    session_id: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    config, _ = load_context(workspace_file)
    normalized_target = _normalize_model_name(target_model) if target_model else ""
    timeline = timeline_query(
        str(workspace_file), task_id=task_id, session_id=session_id, kinds=["handoff"], limit=5000
    ).get("timeline", [])
    matched = []
    for item in timeline:
        row = item.get("raw", {})
        if normalized_target and row.get("normalized_model") != normalized_target:
            continue
        matched.append(row)
    return {
        "workspace": config.workspace,
        "handoffs": matched[-limit:],
        "summary": {
            "total": len(matched),
            "models": sorted(
                {row.get("normalized_model", "") for row in matched if row.get("normalized_model")}
            ),
        },
    }


def workspace_model_profile(model_name: str, workspace_file: str | Path | None = None) -> dict[str, Any]:
    normalized = _normalize_model_name(model_name)
    profiles = dict(DEFAULT_HANDOFF_PROFILES.get("profiles", {}))
    if workspace_file:
        import yaml

        store = WorkspaceStore(workspace_file)
        ensure_default_rules(store)
        path = store.rules_dir / "handoff-profiles.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        profiles.update(data.get("profiles", {}))
    profile = profiles.get(normalized, profiles.get("generic-mcp-agent", {}))
    return {"requested_model": model_name, "normalized_model": normalized, "model": normalized, **profile}


# ---- internal helpers -------------------------------------------------------

def _infer_task_phase(current_summary: str, timeline: list[dict[str, Any]]) -> str:
    summary_lower = (current_summary or "").lower()
    actions = {item.get("action", "") for item in timeline}
    if TOOL_WORKSPACE_SYNC_CASE_ARTIFACTS in actions or "session:" in summary_lower:
        return "conclusion_synced"
    if TOOL_WORKSPACE_SYNC_SNIFF_ARTIFACTS in actions or "risk level" in summary_lower:
        return "context_synced"
    if TOOL_WORKSPACE_LOG_SESSION_EVENT in actions:
        return "in_progress"
    if current_summary.strip():
        return "drafted"
    return "unknown"
