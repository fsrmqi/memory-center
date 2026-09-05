from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from memory_center.core.foundation.schemas import with_schema
from memory_center.core.governance.rules import (
    DEFAULT_HANDOFF_PROFILES,
    ensure_default_rules,
)
from memory_center.core.observability.tracking import log_token_gain
from memory_center.core.storage.workspace import WorkspaceStore

from ..tasks.artifacts import get_task_artifact, list_task_spaces
from ..tasks.timeline import timeline_query
from .compact import _compact_handoff_packet, _compact_resume_packet, _measure_compact_gain
from .query import memory_query_hybrid
from .ranking import tokenize
from .rules import (
    _load_handoff_rules,
    _load_resume_rules,
)
from .session import workspace_recent_evidence, workspace_record_case_recalled
from .shared import (
    LAYER_L0,
    LAYER_L1,
    LAYER_L2,
    LAYER_L3,
    SESSION_SUMMARIES_FILE,
    TOOL_WORKSPACE_LOG_SESSION_EVENT,
    TOOL_WORKSPACE_SYNC_CASE_ARTIFACTS,
    TOOL_WORKSPACE_SYNC_SNIFF_ARTIFACTS,
    _is_compact_view,
    _normalize_model_name,
    _suggest_resume_context,
    load_context,
)


def _is_cjk(ch: str) -> bool:
    return "一" <= ch <= "鿿" or "㐀" <= ch <= "䶿" or "豈" <= ch <= "﫿"


def _cjk_bigrams(text: str) -> list[str]:
    """Return bounded two-character fallbacks for contiguous CJK query spans."""
    spans: list[str] = []
    current = ""
    for ch in str(text or ""):
        if _is_cjk(ch):
            current += ch.lower()
        elif current:
            spans.append(current)
            current = ""
    if current:
        spans.append(current)
    return sorted({span[index:index + 2] for span in spans for index in range(max(0, len(span) - 1))})


def _resume_related_cases(store: WorkspaceStore, intent: str, *, limit: int) -> tuple[list[dict[str, Any]], str]:
    """Keep legacy exact matching, then use a scored CJK fallback only when empty.

    两组命中都按 case 热度(hotness:命中次数 × 时间衰减)重排,高频且最近
    命中的 case 排前;热度来自既有 session events,失败降级为原排序。
    """
    cases = store.read_jsonl_prefer_backend("cross-service-task-memory.jsonl", limit=300)
    tokens = tokenize(intent)
    exact = [item for item in cases if any(token in json.dumps(item, ensure_ascii=False).lower() for token in tokens)]
    if exact:
        return _hotness_ranked(store, exact)[:limit], "exact"
    bigrams = _cjk_bigrams(intent)
    if len(bigrams) < 2:
        return [], "none"
    scored: list[tuple[int, int, dict[str, Any]]] = []
    for index, item in enumerate(cases):
        haystack = json.dumps(item, ensure_ascii=False).lower()
        score = sum(1 for token in bigrams if token in haystack)
        if score >= 2:
            scored.append((score, index, item))
    scored.sort(key=lambda item: (-item[0], -item[1]))
    ranked = _hotness_ranked(store, [item[2] for item in scored[:limit]])
    return ranked, "cjk_bigram" if scored else "none"


def _hotness_ranked(store: WorkspaceStore, cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按热度重排 case;任何异常降级为原顺序(不阻断 resume)。"""
    if len(cases) <= 1:
        return cases
    try:
        from memory_center.core.foundation.hotness import rank_cases_by_hotness

        events = store.read_jsonl_prefer_backend("session-events.jsonl", limit=2000)
        return rank_cases_by_hotness(cases, events)
    except Exception:
        return cases


def workspace_resume_packet(
    workspace_file: str | Path,
    task_id: str = "",
    session_id: str = "",
    intent: str = "",
    limit: int = 10,
    view: str = "compact",
    budget: str = "medium",
) -> dict[str, Any]:
    from .workspace_ops import workspace_status  # lazy import to avoid circular dep

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
        current_summary = get_task_artifact(
            workspace_file,
            resolved_task_id,
            "current_summary",
            max_bytes=16 * 1024,
        ).get("content", "")
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
    packet.update(_build_resume_readiness(packet, task_meta or {}, replay.get("timeline", [])))
    packet.update(_build_resume_task_health(workspace_file, resolved_task_id))
    fields = resume_rules.get("fields", list(packet.keys()))
    filtered = {"workspace": config.workspace}
    for key in fields:
        if key in packet:
            filtered[key] = packet[key]
    filtered["resume_rule_profile"] = packet.get("resume_rule_profile", "default")
    for key in ("resume_readiness", "missing_context", "stale_artifacts", "must_read_refs", "confidence", "task_health", "repair_plan_hint"):
        filtered[key] = packet.get(key)
    result = with_schema("resume_packet", filtered)
    if (view or "").strip().lower() == "compact":
        compact = _compact_resume_packet(result, budget=budget)
        gain = _measure_compact_gain(result, compact)
        log_token_gain(workspace_file, "workspace_resume_packet", budget=budget, model="", raw_tokens=gain["raw_tokens"], compact_tokens=gain["compact_tokens"], view=view)
        return compact
    return result


def workspace_resume_context(workspace_file: str | Path, intent: str, limit: int = 5, session_id: str = "") -> dict[str, Any]:
    config, store = load_context(workspace_file)
    query_result = memory_query_hybrid(workspace_file, intent, limit=limit)
    summaries = store.read_jsonl_prefer_backend(SESSION_SUMMARIES_FILE, limit=500)
    tokens = tokenize(intent)
    related_sessions = []
    for item in summaries:
        haystack = json.dumps(item, ensure_ascii=False).lower()
        score = sum(1 for token in tokens if token in haystack)
        if score > 0:
            related_sessions.append({**item, "match_score": score})
    related_sessions.sort(key=lambda item: (-int(item.get("match_score", 0)), item.get("created_at", "")))
    related_cases, related_case_match_mode = _resume_related_cases(store, intent, limit=limit)
    if session_id.strip():
        for case in related_cases:
            try:
                workspace_record_case_recalled(
                    workspace_file,
                    session_id,
                    str(case.get("case_id", "") or ""),
                    case_task=str(case.get("task", "") or ""),
                )
            except Exception:
                pass
    return {
        "workspace": config.workspace,
        "intent": intent,
        "retrieval_summary": query_result.get("retrieval_summary", {}),
        "related_sessions": related_sessions[:limit],
        "related_cases": related_cases,
        "related_case_match_mode": related_case_match_mode,
        "entrypoints": query_result.get("results", [])[:limit],
        "suggested_context": _suggest_resume_context(
            intent,
            related_sessions[:limit],
            related_cases,
            query_result.get("results", [])[:limit],
        ),
    }


def workspace_unresolved_items(
    workspace_file: str | Path,
    task_id: str = "",
    session_id: str = "",
    intent: str = "",
    limit: int = 10,
) -> dict[str, Any]:
    from .evaluations import memory_eval_write_quality

    config, _ = load_context(workspace_file)
    unresolved: list[str] = []
    quality = memory_eval_write_quality(
        workspace_file, task_id=task_id, session_id=session_id, intent=intent, limit=max(limit, 20)
    )
    for finding in quality.get("findings", []):
        unresolved.append(str(finding.get("message", "") or "").strip())
    if task_id.strip():
        current_summary = get_task_artifact(
            workspace_file,
            task_id.strip(),
            "current_summary",
            max_bytes=16 * 1024,
        ).get("content", "")
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
    from .evaluations import memory_eval_write_quality

    config, _ = load_context(workspace_file)
    action_items: list[dict[str, Any]] = []
    quality = memory_eval_write_quality(
        workspace_file, task_id=task_id, session_id=session_id, intent=intent, limit=max(limit, 20)
    )
    layer_set = set(quality.get("layers_present", []))
    if session_id.strip() and LAYER_L0 not in layer_set:
        action_items.append(_next_action_item(
            "先补 `workspace_log_session_event`，把关键过程写入 L0 session memory。",
            reason="当前 session 有输入但 L0 会话事件缺失，后续恢复和审计会缺少过程证据。",
            evidence="memory_eval_write_quality.layers_present",
            command="memory-center log-session-event",
            priority="high",
        ))
    if task_id.strip() and LAYER_L2 not in layer_set:
        action_items.append(_next_action_item(
            "先补 `workspace_sync_sniff_artifacts` 或 `workspace_sync_case_artifacts`，把任务上下文写入 L2 task space。",
            reason="当前 task_id 有效但 L2 task space 缺失，任务交接时无法稳定复用上下文。",
            evidence="memory_eval_write_quality.layers_present",
            command="memory-center work-sync",
            priority="high",
        ))
    if session_id.strip() and LAYER_L1 not in layer_set:
        action_items.append(_next_action_item(
            "补 `workspace_record_case`，把当前会话沉淀为 L1 case memory。",
            reason="当前 session 尚未沉淀为可复用 case，类似任务不会被后续检索召回。",
            evidence="memory_eval_write_quality.layers_present",
            command="memory-center record-case",
            priority="medium",
        ))
    if any(k in intent.lower() for k in ["规则", "规范", "migration", "invariant"]) and LAYER_L3 not in layer_set:
        action_items.append(_next_action_item(
            "补 `memory_execute_write` 或 `workspace_artifact_update`，把规则类信息写入 L3 核心记忆块。",
            reason="当前 intent 像长期规则/迁移约束，但 L3 workspace profile 尚未覆盖。",
            evidence="intent + memory_eval_write_quality.layers_present",
            command="memory-center memory-execute-write",
            priority="medium",
        ))
    unresolved = workspace_unresolved_items(
        workspace_file, task_id=task_id, session_id=session_id, intent=intent, limit=limit
    ).get("items", [])
    if unresolved:
        action_items.append(_next_action_item(
            f"优先处理未解决项：{unresolved[0]}",
            reason="存在未解决项，继续开发前应先关闭最靠前的阻塞/待验证问题。",
            evidence="workspace_unresolved_items.items[0]",
            command="memory-center unresolved-items",
            priority="high",
        ))
    if not action_items:
        action_items.append(_next_action_item(
            "继续沿当前任务推进，优先核对验证项与风险点是否已覆盖。",
            reason="当前没有发现记忆层缺口或未解决项，下一步应聚焦验证闭环。",
            evidence="memory_eval_write_quality + workspace_unresolved_items",
            command="memory-center verify-checklist",
            priority="medium",
        ))
    action_items = action_items[:limit]
    return {
        "workspace": config.workspace,
        "task_id": task_id,
        "session_id": session_id,
        "actions": [item["action"] for item in action_items],
        "action_items": action_items,
    }


def _next_action_item(action: str, *, reason: str, evidence: str, command: str, priority: str) -> dict[str, Any]:
    return {
        "action": action,
        "reason": reason,
        "evidence": evidence,
        "command": command,
        "priority": priority,
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
    from .evaluations import memory_eval_write_quality

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


def _build_resume_readiness(packet: dict[str, Any], task_meta: dict[str, Any], timeline: list[dict[str, Any]]) -> dict[str, Any]:
    missing: list[str] = []
    stale: list[str] = []
    must_read_refs: list[str] = []

    if not packet.get("task_id"):
        missing.append("task_id")
    if not str(packet.get("current_summary", "") or "").strip():
        missing.append("current_summary")
    if not packet.get("next_recommended_actions"):
        missing.append("next_recommended_actions")
    if not packet.get("latest_receipts") and not timeline:
        missing.append("write_receipts")
    if packet.get("verification_pending"):
        missing.append("verification_resolution")

    stale_days = _days_since(str(task_meta.get("updated_at", "") or ""))
    if stale_days is not None and stale_days >= 14:
        stale.append(f"task_space_stale:{stale_days}d")

    for item in packet.get("recent_evidence", []) or []:
        ref_id = str(item.get("ref_id", "") or "")
        if ref_id:
            must_read_refs.append(ref_id)
        if len(must_read_refs) >= 5:
            break

    if packet.get("verification_pending") or "verification_resolution" in missing:
        readiness = "blocked"
    elif missing:
        readiness = "partial"
    else:
        readiness = "ready"

    confidence = max(0.0, min(1.0, 1.0 - 0.18 * len(missing) - 0.08 * len(stale)))
    return {
        "resume_readiness": readiness,
        "missing_context": missing,
        "stale_artifacts": stale,
        "must_read_refs": must_read_refs,
        "confidence": round(confidence, 2),
    }


def _build_resume_task_health(workspace_file: str | Path, task_id: str) -> dict[str, Any]:
    if not task_id:
        return {
            "task_health": {
                "available": False,
                "health": "unknown",
                "score": 0,
                "issue_count": 0,
                "top_issues": [],
            },
            "repair_plan_hint": {
                "available": False,
                "recommended_action": "",
                "reason": "missing_task_id",
            },
        }
    try:
        from ..tasks.artifacts import task_space_health

        health = task_space_health(workspace_file, task_id)
    except Exception as exc:
        return {
            "task_health": {
                "available": False,
                "health": "unknown",
                "score": 0,
                "issue_count": 0,
                "top_issues": [],
                "error": str(exc),
            },
            "repair_plan_hint": {
                "available": False,
                "recommended_action": "",
                "reason": "task_health_failed",
            },
        }
    issues = health.get("issues", []) if isinstance(health.get("issues", []), list) else []
    top_issues = [
        {
            "code": str(issue.get("code", "")),
            "severity": str(issue.get("severity", "")),
        }
        for issue in issues[:5]
    ]
    has_issues = bool(issues)
    return {
        "task_health": {
            "available": True,
            "health": health.get("health", "unknown"),
            "score": health.get("score", 0),
            "issue_count": len(issues),
            "top_issues": top_issues,
        },
        "repair_plan_hint": {
            "available": has_issues,
            "recommended_action": f"mc_admin(action='task_repair_plan', task_id='{task_id}')" if has_issues else "",
            "reason": "health_issues_detected" if has_issues else "no_health_issues",
        },
    }


def _days_since(value: str) -> int | None:
    if not value:
        return None
    try:
        from datetime import datetime, timezone

        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - dt).total_seconds() // 86400))
    except Exception:
        return None
