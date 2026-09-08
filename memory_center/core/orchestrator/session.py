from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memory_center.core.audit.snapshots import (
    build_session_evidence_chain,
    capture_git_snapshot,
    normalize_validation_snapshot,
)
from memory_center.core.storage.workspace import WorkspaceStore

from ..tasks.receipts import build_write_receipt, persist_write_receipt
from .retention import (
    DEFAULT_KEEP_RECENT_TURNS as _RETENTION_DEFAULT_KEEP_TURNS,
    DEFAULT_MAX_ARCHIVE_TOKENS as _RETENTION_DEFAULT_ARCHIVE_TOKENS,
    plan_retention,
)
from .session_payloads import (
    _build_case_evidence_refs,
    _build_event_source_refs,
    _event_payload,
    _prepare_session_event_payload,
    _summarize_ref,
)
from .shared import (
    LAYER_L0,
    SESSION_EVENTS_FILE,
    SESSION_SUMMARIES_FILE,
    TOOL_WORKSPACE_LOG_SESSION_EVENT,
    _new_session_id,
    _suggest_risk_points,
    load_context,
)

_NEGATIVE_OUTCOME_HINTS = (
    "fail",
    "failed",
    "failure",
    "reject",
    "rejected",
    "rollback",
    "rolled back",
    "blocked",
    "失败",
    "未通过",
    "不通过",
    "拒绝",
    "回滚",
    "阻塞",
)

_DELIVERY_VALIDATION_HINTS = (
    "验证通过",
    "测试通过",
    "已确认",
    "确认修改生效",
    "verified",
    "validation passed",
    "tests passed",
)


def workspace_start_session(
    workspace_file: str | Path,
    intent: str,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config, store = load_context(workspace_file)
    sid = session_id or _new_session_id()
    item = {
        "session_id": sid,
        "workspace": config.workspace,
        "event_type": "session_start",
        "intent": intent,
        "payload": {**(metadata or {}), "code_snapshot": capture_git_snapshot(workspace_file)},
    }
    store.append_jsonl(SESSION_EVENTS_FILE, item)
    # E-05: Connect-time catch-up — include freshness info
    freshness_info: dict[str, Any] = {}
    try:
        from ..freshness.integration import get_freshness_with_actions
        freshness_info = get_freshness_with_actions(str(workspace_file))
    except Exception:
        pass
    # D-02: Context Pack recommendation for architecture understanding
    context_pack_hint: dict[str, Any] = {}
    try:
        from ..context.pack import ContextPackBuilder
        ContextPackBuilder(str(workspace_file))
        # Just check if context pack is feasible, don't build full pack
        context_pack_hint = {
            "available": True,
            "recommended_for": ["architecture_understanding", "change_preview"],
            "suggested_budget_tokens": 4000,
        }
    except Exception:
        context_pack_hint = {"available": False}

    # G-01: Workflow profile recommendation based on intent
    workflow_recommendation: dict[str, Any] = {}
    try:
        from ..verification.workflow_profiles import recommend_workflow_with_learning
        workflow_recommendation = recommend_workflow_with_learning(workspace_file, intent)
    except Exception:
        pass

    return {
        "started": True,
        "session_id": sid,
        "workspace": config.workspace,
        "intent": intent,
        "created_at": item.get("created_at"),
        "freshness": freshness_info,
        "context_pack_hint": context_pack_hint,
        "workflow_recommendation": workflow_recommendation,
        "code_snapshot": item["payload"]["code_snapshot"],
    }


def workspace_log_session_event(
    workspace_file: str | Path,
    session_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config, store = load_context(workspace_file)
    prepared_payload, payload_ref, payload_bytes = _prepare_session_event_payload(store, session_id, event_type, payload or {})
    item = {
        "session_id": session_id,
        "workspace": config.workspace,
        "event_type": event_type,
        "payload": prepared_payload,
        "payload_ref": payload_ref,
        "payload_bytes": payload_bytes,
    }
    store.append_jsonl(SESSION_EVENTS_FILE, item)
    receipt = persist_write_receipt(
        store,
        build_write_receipt(
            layer=LAYER_L0,
            action=TOOL_WORKSPACE_LOG_SESSION_EVENT,
            scope="memory",
            target=event_type,
            target_file=f"memory/{SESSION_EVENTS_FILE}",
            session_id=session_id,
            payload_ref=payload_ref,
            bytes_written=payload_bytes,
        ),
    )
    return {
        "logged": True,
        "session_id": session_id,
        "workspace": config.workspace,
        "event_type": event_type,
        "payload_ref": payload_ref,
        "payload_bytes": payload_bytes,
        "created_at": item.get("created_at"),
        "write_receipt": receipt,
    }


def workspace_capture_dsh_delivery_summary(
    workspace_file: str | Path,
    source_session_id: str,
    summary: str,
    turn: int | None = None,
    step: int | None = None,
    task_id: str = "",
) -> dict[str, Any]:
    """Persist one bounded DSH completion summary as an independent L0 session.

    This is deliberately not a transcript importer: callers supply only a
    completion-signalled assistant summary, which is capped before persistence.
    A capture has its own deterministic ID so retries are idempotent at the
    plugin boundary and no capture can silently become a reusable L1 case.
    Session-first（P0-3）：task_id 必须来自调用方当前绑定的任务，不再回退
    工作区排序候选（current_focus_task），避免交付摘要写入错误任务空间。
    """
    normalized = " ".join(str(summary).split())[:1400]
    if not normalized:
        raise ValueError("delivery summary must not be empty")
    suffix = f"{turn if turn is not None else 'x'}:{step if step is not None else 'x'}"
    session_id = f"dsh-delivery:{source_session_id}:{suffix}"
    task_id = str(task_id or "").strip()
    if not task_id:
        return {
            "captured": False,
            "logged": False,
            "session_id": "",
            "workspace": "",
            "event_type": "dsh_delivery_summary",
            "reason": "task_id_required",
            "next_action": "交付摘要必须锚定当前绑定的工程任务；请先绑定任务后重试。",
        }
    _, store = load_context(workspace_file)
    existing = store.find_jsonl_via_backend(
        SESSION_EVENTS_FILE,
        lambda item: item.get("session_id") == session_id and item.get("event_type") == "dsh_delivery_summary",
        limit=1,
    )
    if existing:
        return {
            "captured": False,
            "duplicate": True,
            "session_id": session_id,
            "source_session_id": source_session_id,
        }
    workspace_start_session(
        workspace_file,
        intent=normalized[:240],
        session_id=session_id,
        metadata={"source": "dsh_delivery_capture", "source_session_id": source_session_id, "task_id": task_id},
    )
    workspace_log_session_event(
        workspace_file,
        session_id,
        "dsh_delivery_summary",
        {
            "summary": normalized,
            "source_session_id": source_session_id,
            "task_id": task_id,
            **({"turn": turn} if turn is not None else {}),
            **({"step": step} if step is not None else {}),
            "capture_boundary": "completion_summary_only",
        },
    )
    validation_status = "passed" if any(hint in normalized.lower() for hint in _DELIVERY_VALIDATION_HINTS) else "recorded"
    ended = workspace_end_session(
        workspace_file,
        session_id,
        outcome="completed",
        validation_summary="DSH completion-summary capture; not an independent test execution receipt.",
        validation_status=validation_status,
    )
    return {
        "captured": True,
        "session_id": session_id,
        "source_session_id": source_session_id,
        "task_id": task_id,
        "summary_chars": len(normalized),
        "validation_status": validation_status,
        "ended": ended,
    }


def workspace_record_agent_guidance(
    workspace_file: str | Path,
    session_id: str,
    *,
    query: str = "",
    mode: str = "",
    source: str = "",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record agent_next_steps from a lookup payload into the session log."""

    if not session_id.strip():
        return {"logged": False, "reason": "missing_session_id"}
    lookup_payload = payload or {}
    steps = _extract_agent_next_steps(lookup_payload)
    if not steps:
        return {"logged": False, "reason": "missing_agent_next_steps"}
    return workspace_log_session_event(
        workspace_file,
        session_id,
        "agent_guidance",
        {
            "query": query,
            "mode": mode,
            "source": source,
            "intent": str((lookup_payload.get("intent_analysis", {}) or {}).get("primary_intent", "") or ""),
            "mode_used": str(lookup_payload.get("mode_used", "") or mode),
            "retrieval_policy": dict(lookup_payload.get("retrieval_policy", {}) or {}),
            "agent_next_steps": steps,
        },
    )


def workspace_record_case_recalled(
    workspace_file: str | Path,
    session_id: str,
    case_id: str,
    *,
    case_task: str = "",
) -> dict[str, Any]:
    """记录一次已交付 case 的稳定 ID 命中，供后续热度统计精确聚合。"""
    if not session_id.strip() or not case_id.strip():
        return {"logged": False, "reason": "missing_session_or_case_id"}
    return workspace_log_session_event(
        workspace_file,
        session_id,
        "case_recalled",
        {"case_id": case_id.strip(), "case_task": case_task[:240]},
    )


def _extract_agent_next_steps(payload: dict[str, Any]) -> list[dict[str, Any]]:
    steps = payload.get("agent_next_steps", [])
    if isinstance(steps, list) and steps:
        return [step for step in steps if isinstance(step, dict)]
    nested = payload.get("result", {})
    if isinstance(nested, dict):
        nested_steps = nested.get("agent_next_steps", [])
        if isinstance(nested_steps, list) and nested_steps:
            return [step for step in nested_steps if isinstance(step, dict)]
    return []


def workspace_end_session(
    workspace_file: str | Path,
    session_id: str,
    outcome: str = "",
    verified_by: list[str] | None = None,
    validation_command: str = "",
    validation_exit_code: int | None = None,
    validation_summary: str = "",
    validation_status: str = "",
) -> dict[str, Any]:
    config, store = load_context(workspace_file)
    validation = normalize_validation_snapshot(
        command=validation_command,
        exit_code=validation_exit_code,
        summary=validation_summary,
        status=validation_status,
    )
    if verified_by and validation["status"] == "not_run":
        validation = {
            **validation,
            "status": "passed",
            "verified": True,
            "verification_source": "human_confirmation",
        }
    workspace_log_session_event(
        workspace_file,
        session_id,
        "session_end",
        {
            "outcome": outcome,
            "verified_by": verified_by or [],
            "code_snapshot": capture_git_snapshot(workspace_file),
            "validation": validation,
        },
    )
    events = _session_events(store, session_id)
    summary = _build_session_summary(config.workspace, session_id, events, outcome, verified_by or [])
    store.append_jsonl(SESSION_SUMMARIES_FILE, summary)
    try:
        from memory_center.core.knowledge.governance import project_session_validation

        governance = project_session_validation(store, session_id, validation)
    except Exception as exc:
        governance = {"status": "unavailable", "reason": str(exc)[:160]}
    return {
        "ended": True,
        "session_id": session_id,
        "workspace": config.workspace,
        "summary": summary,
        "evidence_chain": summary["evidence_chain"],
        "governance": governance,
    }


def workspace_recent_sessions(workspace_file: str | Path, limit: int = 10) -> dict[str, Any]:
    config, store = load_context(workspace_file)
    summaries = store.read_jsonl_via_backend(SESSION_SUMMARIES_FILE, limit=max(limit, 1))
    return {
        "workspace": config.workspace,
        "recent_sessions": list(reversed(summaries[-limit:])),
    }


def workspace_task_delivery_overview(workspace_file: str | Path, task_id: str = "", limit: int = 20) -> dict[str, Any]:
    """Bounded task-level delivery projection for the DSH command center."""
    from .workspace_ops import workspace_status
    from .write import workspace_write_receipts

    status = workspace_status(workspace_file, view="compact", budget="small")
    # Session-first（P0-2）：delivery overview 必须锚定显式 task_id；
    # 不再回退 current_focus_task（工作区排序候选），无锚点时返回空投影。
    if not task_id:
        active = status.get("active_task_spaces") or []
        return {
            "schema_version": 1,
            "kind": "task_delivery_overview",
            "task_id": "",
            "task": None,
            "stage": "unbound",
            "delivery_count": 0,
            "verified_delivery_count": 0,
            "receipt_count": 0,
            "timeline": [],
            "next_action": "先选择或绑定一个工程任务，再查看交付时间线。",
            "resumable_tasks": active[:limit],
        }
    resolved_task_id = task_id
    sessions = workspace_recent_sessions(workspace_file, limit=200).get("recent_sessions", [])
    deliveries = [item for item in sessions if item.get("task_id") == resolved_task_id and str(item.get("session_id", "")).startswith("dsh-delivery:")][:limit]
    receipts = workspace_write_receipts(workspace_file, task_id=resolved_task_id, limit=limit).get("receipts", [])
    verified = [item for item in deliveries if ((item.get("evidence_chain") or {}).get("validation") or {}).get("verified")]
    stage = "in_progress"
    if deliveries and not verified:
        stage = "awaiting_validation"
    if verified:
        stage = "delivery_recorded"
    task_row = next(
        (item for item in (status.get("active_task_spaces") or []) if str(item.get("task_id", "")) == resolved_task_id),
        {},
    )
    timeline = [
        {"kind": "task", "label": "任务已绑定", "time": str(task_row.get("updated_at", "") or "")},
        *[{"kind": "delivery", "label": str(item.get("intent", "交付摘要") or "交付摘要")[:140], "time": str(item.get("created_at", "") or ""), "verified": item in verified} for item in reversed(deliveries[-5:])],
        *[{"kind": "receipt", "label": str(item.get("summary", "") or item.get("action", "写入回执"))[:140], "time": str(item.get("created_at", "") or "")} for item in receipts[-5:]],
    ]
    return {
        "schema_version": 1,
        "kind": "task_delivery_overview",
        "task_id": resolved_task_id,
        "task": task_row,
        "stage": stage,
        "delivery_count": len(deliveries),
        "verified_delivery_count": len(verified),
        "receipt_count": len(receipts),
        "timeline": timeline,
        "next_action": "先验证当前交付。" if stage == "awaiting_validation" else "继续当前任务或生成交接包。",
    }


def workspace_session_summary(workspace_file: str | Path, session_id: str) -> dict[str, Any]:
    config, store = load_context(workspace_file)
    summaries = store.find_jsonl_via_backend(SESSION_SUMMARIES_FILE, lambda row: row.get("session_id") == session_id, limit=1)
    events = _session_events(store, session_id)
    session_overview = _build_session_overview(events)
    return {
        "workspace": config.workspace,
        "session_id": session_id,
        "found": bool(summaries or events),
        "summary": summaries[-1] if summaries else None,
        "events": events[-50:],
        "session_overview": session_overview,
    }


def workspace_suggest_case(workspace_file: str | Path, session_id: str) -> dict[str, Any]:
    config, store = load_context(workspace_file)
    session = workspace_session_summary(workspace_file, session_id)
    if not session.get("found"):
        return {
            "workspace": config.workspace,
            "session_id": session_id,
            "found": False,
            "draft_case": None,
            "hint": "session_id 不存在，先调用 workspace_start_session / workspace_end_session。",
        }
    summary = session.get("summary") or {}
    events = session.get("events", [])
    files = [item for item in summary.get("files", []) if isinstance(item, str) and item]
    projects = [item for item in summary.get("projects", []) if isinstance(item, str) and item]
    if not projects:
        projects = sorted(
            {
                payload_project
                for event in events
                for payload_project in [_event_payload(event).get("project", "")]
                if payload_project
            }
        )
    tool_calls = summary.get("tool_calls", [])
    risk_points = _suggest_risk_points(summary, events)
    flow = " -> ".join(tool_calls[:8]) if tool_calls else "sniff -> query -> context -> impact -> verify"
    draft = {
        "task": summary.get("intent") or f"会话任务 {session_id}",
        "projects": projects,
        "files": files[:30],
        "flow": flow,
        "risk_points": risk_points,
        "verified_by": summary.get("verified_by", []),
        "memory_layer": "L1_case_atom",
        "source_session_id": session_id,
        "source_task_id": "",
        "source_refs": _build_event_source_refs(events),
        "evidence_refs": _build_case_evidence_refs(events),
    }
    return {
        "workspace": config.workspace,
        "session_id": session_id,
        "found": True,
        "draft_case": draft,
        "hint": "确认后可直接调用 workspace_record_case / record-case 入库。",
        "case_writing_guide": _case_writing_guide_payload(store),
    }


def _case_writing_guide_payload(store: WorkspaceStore) -> dict[str, Any]:
    """随 suggest_case 返回 case schema 写作指南(无 LLM,纯模板)。"""
    from memory_center.core.knowledge.case_schema import case_writing_guide, load_case_registry

    try:
        schema = load_case_registry(store).get()
    except Exception:  # pragma: no cover - 规则文件损坏时退回内置 schema
        from memory_center.core.knowledge.case_schema import BUILTIN_CASE_SCHEMA

        schema = BUILTIN_CASE_SCHEMA
    return case_writing_guide(schema, include_template=True)


def workspace_record_close_feedback(
    workspace_file: str | Path,
    session_id: str,
    task_id: str = "",
    source: str = "mc_close_auto",
) -> dict[str, Any]:
    """Infer candidate-path feedback from a closed session and persist it."""
    config, _store = load_context(workspace_file)
    session = workspace_session_summary(workspace_file, session_id)
    if not session.get("found"):
        return {
            "workspace": config.workspace,
            "session_id": session_id,
            "recorded": False,
            "feedback_items": [],
            "reason": "session_not_found",
        }

    summary = session.get("summary") or {}
    events = session.get("events", []) or []
    case_result = workspace_suggest_case(workspace_file, session_id)
    case = case_result.get("draft_case", {}) if case_result.get("found") else {}
    outcome = _derive_feedback_outcome(summary)
    candidates = _infer_close_feedback_candidates(summary, events, case, outcome)
    if not candidates:
        return {
            "workspace": config.workspace,
            "session_id": session_id,
            "recorded": False,
            "feedback_items": [],
            "reason": "no_candidate_paths_inferred",
        }

    from ..verification.heuristics import HeuristicsRegister

    register = HeuristicsRegister(workspace_file)
    feedback_items = []
    for candidate in candidates:
        feedback_items.append(
            register.record_candidate_path_feedback(
                candidate_type=str(candidate.get("candidate_type", "") or ""),
                target=str(candidate.get("target", "") or ""),
                outcome=outcome,
                evidence=candidate.get("evidence") or [],
                source=source,
                task_id=task_id,
                session_id=session_id,
                why=str(candidate.get("why", "") or ""),
                next_action=str(candidate.get("next_action", "") or ""),
                verification_cost=str(candidate.get("verification_cost", "") or "medium"),
                trigger=str(candidate.get("trigger", "") or ""),
            )
        )

    return {
        "workspace": config.workspace,
        "session_id": session_id,
        "recorded": bool(feedback_items),
        "feedback_items": feedback_items,
        "reason": "recorded" if feedback_items else "no_feedback_written",
        "inferred_outcome": outcome,
    }


def workspace_recent_evidence(
    workspace_file: str | Path,
    task_id: str = "",
    session_id: str = "",
    limit: int = 10,
    budget: str = "medium",
    view: str = "compact",
) -> dict[str, Any]:
    from ..tasks.timeline import timeline_query

    config, store = load_context(workspace_file)
    result = timeline_query(str(workspace_file), task_id=task_id.strip(), session_id=session_id.strip(), kinds=["session_event", "write_receipt"], limit=limit)
    evidence: list[dict[str, Any]] = []
    for item in result.get("timeline", []):
        if item.get("kind") == "session_event":
            raw = item.get("raw", {})
            payload = raw.get("payload", {}) if isinstance(raw.get("payload"), dict) else {}
            synopsis = payload.get("_payload_synopsis") if isinstance(payload.get("_payload_synopsis"), dict) else {}
            entry = {
                "ref_id": f"ev:{item.get('session_id', '')}:{item.get('action', '')}:{len(evidence) + 1}",
                "source": "session_event",
                "event_type": item.get("action", ""),
                "session_id": item.get("session_id", ""),
                "payload_ref": raw.get("payload_ref", ""),
                "project": payload.get("project", ""),
                "file_path": payload.get("file_path", "") or payload.get("path", ""),
                "tool_name": payload.get("tool_name", ""),
                "query": payload.get("query", "") or payload.get("target", ""),
                "created_at": item.get("created_at", ""),
            }
            if synopsis.get("title"):
                entry["synopsis"] = {
                    "title": str(synopsis.get("title", ""))[:120],
                    "kind": str(synopsis.get("kind", "")),
                    "summary": [str(line)[:160] for line in (synopsis.get("summary") or [])[:3]],
                }
            entry["summary"] = _summarize_ref(entry)
            evidence.append(entry)
        elif item.get("kind") == "write_receipt":
            entry = {
                "ref_id": str((item.get("raw", {}) or {}).get("receipt_id", "") or f"wr:{item.get('layer', '')}:{item.get('action', '')}:{len(evidence) + 1}"),
                "source": "write_receipt",
                "layer": item.get("layer", ""),
                "action": item.get("action", ""),
                "task_id": item.get("task_id", ""),
                "session_id": item.get("session_id", ""),
                "target": item.get("target", ""),
                "receipt_ref": item.get("receipt_ref", ""),
                "created_at": item.get("created_at", ""),
            }
            entry["summary"] = _summarize_ref(entry)
            evidence.append(entry)
    result = {
        "workspace": config.workspace,
        "task_id": task_id,
        "session_id": session_id,
        "evidence": evidence[-limit:],
    }
    from memory_center.core.observability.tracking import log_token_gain

    from .compact import _measure_compact_gain
    from .shared import _is_compact_view

    if _is_compact_view(view):
        compact_evidence = _compact_evidence_entries(result["evidence"], budget=budget)
        compact_result = {**result, "evidence": compact_evidence}
        gain = _measure_compact_gain(result, compact_result)
        log_token_gain(workspace_file, "workspace_recent_evidence", budget=budget, model="", raw_tokens=gain["raw_tokens"], compact_tokens=gain["compact_tokens"], view=view)
        return compact_result
    return result


def _session_events(store: WorkspaceStore, session_id: str) -> list[dict[str, Any]]:
    return store.find_jsonl_via_backend(
        SESSION_EVENTS_FILE,
        lambda row: row.get("session_id") == session_id,
        limit=1000,
        session_id=session_id,
    )


def _build_session_summary(
    workspace: str,
    session_id: str,
    events: list[dict[str, Any]],
    outcome: str,
    verified_by: list[str],
) -> dict[str, Any]:
    intent = ""
    task_id = ""
    for item in events:
        if item.get("event_type") == "session_start":
            intent = item.get("intent", "")
            task_id = str(_event_payload(item).get("task_id", "") or "")
            break
    event_types = [item.get("event_type", "") for item in events if item.get("event_type")]
    tool_calls = []
    files = set()
    projects = set()
    notable_terms = []
    for item in events:
        payload = _event_payload(item)
        if item.get("event_type") == "tool_call":
            tool_name = payload.get("tool_name") or payload.get("name")
            if tool_name:
                tool_calls.append(tool_name)
        for key in ["file", "file_path", "path"]:
            value = payload.get(key)
            if isinstance(value, str) and value:
                files.add(value)
        value = payload.get("project")
        if isinstance(value, str) and value:
            projects.add(value)
        for field in ["query", "target", "name", "intent"]:
            value = payload.get(field)
            if isinstance(value, str) and value:
                notable_terms.append(value)
    unique_tools = list(dict.fromkeys(tool_calls))
    summary_text = outcome or _summary_text(intent, unique_tools, files, projects, event_types)
    evidence_chain = build_session_evidence_chain(events, outcome)
    return {
        "session_id": session_id,
        "workspace": workspace,
        "intent": intent,
        "task_id": task_id,
        "event_count": len(events),
        "event_types": sorted(set(event_types)),
        "tool_calls": unique_tools,
        "projects": sorted(projects),
        "files": sorted(files)[:50],
        "outcome": outcome,
        "verified_by": verified_by,
        "summary": summary_text,
        "notable_terms": notable_terms[-10:],
        "evidence_chain": evidence_chain,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _derive_feedback_outcome(summary: dict[str, Any]) -> str:
    verified_by = summary.get("verified_by", []) or []
    if verified_by:
        return "confirmed"
    outcome_text = str(summary.get("outcome", "") or "").lower()
    if any(term in outcome_text for term in _NEGATIVE_OUTCOME_HINTS):
        return "rejected"
    return "needs-more-context"


def _infer_close_feedback_candidates(
    summary: dict[str, Any],
    events: list[dict[str, Any]],
    case: dict[str, Any],
    outcome: str,
) -> list[dict[str, Any]]:
    evidence = list(case.get("evidence_refs", []) or case.get("source_refs", []) or [])
    default_target = _default_feedback_target(summary, case)
    seen: set[tuple[str, str]] = set()
    candidates: list[dict[str, Any]] = []

    for event in reversed(events):
        if event.get("event_type") != "tool_call":
            continue
        payload = _event_payload(event)
        candidate = _candidate_from_tool_payload(payload, default_target, outcome, evidence)
        if not candidate:
            continue
        key = (candidate.get("candidate_type", ""), candidate.get("target", ""))
        if not key[0] or not key[1] or key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)
        if len(candidates) >= 3:
            break

    return candidates


def _default_feedback_target(summary: dict[str, Any], case: dict[str, Any]) -> str:
    for item in reversed(summary.get("notable_terms", []) or []):
        if isinstance(item, str) and item.strip():
            return item.strip()
    if case.get("task"):
        return str(case.get("task", "")).strip()
    return str(summary.get("intent", "") or "").strip()


def _candidate_from_tool_payload(
    payload: dict[str, Any],
    default_target: str,
    outcome: str,
    evidence: list[dict[str, Any]],
) -> dict[str, Any] | None:
    tool_name = str(payload.get("tool_name") or payload.get("name") or "").lower()
    if not tool_name:
        return None

    if any(token in tool_name for token in ("mc_analyze", "memory_impact", "memory_plan_change", "impact")):
        target = str(payload.get("target") or payload.get("query") or default_target or "").strip()
        if not target:
            return None
        return {
            "candidate_type": "impact_analysis",
            "target": target,
            "why": "会话在关闭时基于已验证结果回写影响分析路径。",
            "next_action": _feedback_next_action(outcome, success_action="优先沿影响分析路径继续扩展上下游验证。"),
            "verification_cost": "medium",
            "evidence": evidence[:5],
            "trigger": tool_name,
        }

    lookup_target = _lookup_feedback_target(tool_name, payload)
    if lookup_target:
        return {
            "candidate_type": "lookup_path",
            "target": lookup_target,
            "why": "会话在关闭时基于检索链路的实际验证结果回写查询路径。",
            "next_action": _feedback_next_action(outcome, success_action="后续相似问题优先尝试这条检索路径。"),
            "verification_cost": "low",
            "evidence": evidence[:5],
            "trigger": tool_name,
        }

    if any(token in tool_name for token in ("mc_sync", "sync_case", "sync_sniff")):
        target = str(payload.get("task_id") or default_target or "task_space").strip()
        return {
            "candidate_type": "task_sync",
            "target": target,
            "why": "会话关闭时回写任务同步路径的有效性。",
            "next_action": _feedback_next_action(outcome, success_action="类似长任务可继续优先走任务同步。"),
            "verification_cost": "low",
            "evidence": evidence[:5],
            "trigger": tool_name,
        }

    return None


def _lookup_feedback_target(tool_name: str, payload: dict[str, Any]) -> str:
    mode = str(payload.get("mode", "") or "").lower()
    mode_map = {
        "auto": "lookup_auto",
        "symbol": "symbol_lookup",
        "code": "code_lookup",
        "query": "keyword_lookup",
        "chain": "call_chain",
        "trace": "trace_lookup",
        "context": "context_lookup",
        "contracts": "contract_lookup",
    }
    if mode in mode_map:
        return mode_map[mode]

    name_map = {
        "workspace_lookup_hint": "lookup_auto",
        "mc_lookup": "lookup_auto",
        "memory_symbol": "symbol_lookup",
        "memory_search_code": "code_lookup",
        "memory_query_hybrid": "keyword_lookup",
        "memory_callers": "call_chain",
        "memory_callees": "call_chain",
        "workspace_trace": "trace_lookup",
        "memory_context": "context_lookup",
        "memory_contracts": "contract_lookup",
    }
    for key, value in name_map.items():
        if key in tool_name:
            return value
    return ""


def _feedback_next_action(outcome: str, success_action: str) -> str:
    if outcome == "confirmed":
        return success_action
    if outcome == "rejected":
        return "降低该路径优先级，并切换到其他候选路径验证。"
    return "补充更多证据后再决定是否继续优先采用该路径。"


def _summary_text(intent: str, tool_calls: list[str], files: set[str], projects: set[str], event_types: list[str]) -> str:
    parts = []
    if intent:
        parts.append(f"任务意图：{intent}")
    if tool_calls:
        parts.append(f"调用工具：{', '.join(tool_calls[:6])}")
    if projects:
        parts.append(f"涉及项目：{', '.join(sorted(projects)[:6])}")
    if files:
        parts.append(f"涉及文件数：{len(files)}")
    if event_types:
        parts.append(f"事件类型：{', '.join(sorted(set(event_types))[:6])}")
    return "；".join(parts) if parts else "会话已结束，暂无可提炼摘要。"


def _build_session_overview(events: list[dict[str, Any]]) -> dict[str, Any]:
    payload_ref_count = 0
    source_ref_like_count = 0
    event_types: dict[str, int] = {}
    payload_refs: list[str] = []
    for event in events:
        event_type = str(event.get("event_type", "") or "")
        if event_type:
            event_types[event_type] = event_types.get(event_type, 0) + 1
        payload_ref = str(event.get("payload_ref", "") or "")
        if payload_ref:
            payload_ref_count += 1
            payload_refs.append(payload_ref)
        payload = _event_payload(event)
        if any(isinstance(payload.get(key), str) and payload.get(key) for key in ["tool_name", "query", "target", "file_path", "path", "project"]):
            source_ref_like_count += 1
    return {
        "memory_layer": LAYER_L0,
        "event_count": len(events),
        "event_type_counts": event_types,
        "payload_ref_count": payload_ref_count,
        "source_ref_like_event_count": source_ref_like_count,
        "payload_refs": payload_refs[:10],
        "highlights": [
            f"events={len(events)}",
            f"payload_refs={payload_ref_count}",
            f"source_ref_like_events={source_ref_like_count}",
        ],
    }


def _compact_evidence_entries(entries: list[dict[str, Any]], budget: str = "medium") -> list[dict[str, Any]]:
    normalized_budget = (budget or "medium").strip().lower()
    if normalized_budget == "tiny":
        k = 1
    elif normalized_budget == "small":
        k = 3
    elif normalized_budget == "large":
        k = 10
    else:
        k = 5
    # Top-K strategy (agentmemory pattern): rank by importance + recency.
    # Error events and rule matches rank higher than regular events.
    _IMPORTANCE_WEIGHTS = {
        "error_event": 10,
        "rule_match": 8,
        "task_sync": 6,
        "case_record": 5,
        "tool_call_with_result": 4,
        "session_start_end": 3,
        "regular_event": 1,
    }
    _ERROR_KEYWORDS = ("error", "exception", "fail", "traceback", "bug", "crash")

    def _importance_score(item: dict[str, Any]) -> int:
        source = (item.get("source") or "").lower()
        event_type = (item.get("event_type") or item.get("action") or "").lower()
        payload_text = " ".join(str(v) for v in item.values() if isinstance(v, str)).lower()

        if any(kw in payload_text for kw in _ERROR_KEYWORDS):
            return _IMPORTANCE_WEIGHTS["error_event"]
        if source == "l3" or "rule" in event_type:
            return _IMPORTANCE_WEIGHTS["rule_match"]
        if source == "l2" or "sync" in event_type:
            return _IMPORTANCE_WEIGHTS["task_sync"]
        if source == "l1" or "case" in event_type:
            return _IMPORTANCE_WEIGHTS["case_record"]
        if "tool_call" in event_type and item.get("payload_ref"):
            return _IMPORTANCE_WEIGHTS["tool_call_with_result"]
        if event_type in ("session_start", "session_end", "start", "end"):
            return _IMPORTANCE_WEIGHTS["session_start_end"]
        return _IMPORTANCE_WEIGHTS["regular_event"]

    ranked = sorted(entries, key=lambda e: (_importance_score(e), str(e.get("created_at", ""))), reverse=True)
    compact_entries = []
    for item in ranked[:k]:
        entry = {
            "ref_id": item.get("ref_id", ""),
            "source": item.get("source", ""),
            "summary": item.get("summary", ""),
            "created_at": item.get("created_at", ""),
            "payload_ref": item.get("payload_ref", ""),
            "receipt_ref": item.get("receipt_ref", ""),
        }
        # 外置 payload 的确定性摘要标题并入 compact 摘要,替代整段 synopsis,
        # 保持 compact 输出的扁平与轻量。
        synopsis = item.get("synopsis") if isinstance(item.get("synopsis"), dict) else {}
        if synopsis.get("title"):
            entry["synopsis_title"] = str(synopsis.get("title", ""))[:120]
            entry["synopsis_kind"] = str(synopsis.get("kind", ""))
        compact_entries.append(entry)
    return compact_entries


SESSION_EVENTS_ARCHIVE_FILE = "session-events-archive.jsonl"


def plan_session_archive(
    workspace_file: str | Path,
    session_id: str = "",
    *,
    keep_recent_turns: int = _RETENTION_DEFAULT_KEEP_TURNS,
    max_archive_tokens: int = _RETENTION_DEFAULT_ARCHIVE_TOKENS,
    limit: int = 5000,
) -> dict[str, Any]:
    """对会话事件做滚动归档规划(dry-run):返回轮次划分与 archive/live 边界,不写盘。"""
    config, store = load_context(workspace_file)
    events = _load_session_events_for_archive(store, session_id=session_id, limit=limit)
    decision = plan_retention(events, keep_recent_turns=keep_recent_turns, max_archive_tokens=max_archive_tokens)
    return {
        "workspace": config.workspace,
        "session_id": session_id,
        "mode": decision.mode,
        "reason": decision.reason,
        "total_events": decision.total_events,
        "total_turns": decision.total_turns,
        "total_tokens": decision.total_tokens,
        "archive_events": decision.archive_events,
        "archive_turns": decision.archive_turns,
        "archive_tokens": decision.archive_tokens,
        "keep_events": decision.keep_events,
        "keep_turns": decision.keep_turns,
        "keep_tokens": decision.keep_tokens,
        "boundary_event_index": decision.boundary_event_index,
        "turns": [
            {
                "turn_index": turn.turn_index,
                "label": turn.label,
                "event_count": turn.event_count,
                "tokens": turn.tokens,
                "start_event_index": turn.start_event_index,
                "end_event_index": turn.end_event_index,
            }
            for turn in decision.turns
        ],
        "dry_run": True,
    }


def archive_session_events(
    workspace_file: str | Path,
    session_id: str = "",
    *,
    keep_recent_turns: int = _RETENTION_DEFAULT_KEEP_TURNS,
    max_archive_tokens: int = _RETENTION_DEFAULT_ARCHIVE_TOKENS,
    limit: int = 5000,
) -> dict[str, Any]:
    """执行滚动归档:把归档段事件迁移到 session-events-archive.jsonl 并从 live 集合裁剪。

    与 OV 的 retention 语义一致:边界落在轮次边界,session_end 类锚点永不归档;
    live 集合按 record 时间戳裁剪,SQLite 镜像同步清理,归档集合双写可查。
    """
    config, store = load_context(workspace_file)
    events = _load_session_events_for_archive(store, session_id=session_id, limit=limit)
    decision = plan_retention(events, keep_recent_turns=keep_recent_turns, max_archive_tokens=max_archive_tokens)
    if decision.reason != "planned" or decision.boundary_event_index <= 0:
        return {
            "workspace": config.workspace,
            "session_id": session_id,
            "archived": False,
            "reason": decision.reason,
            "total_events": decision.total_events,
            "total_turns": decision.total_turns,
        }

    boundary = decision.boundary_event_index
    archived_events = events[:boundary]
    kept_events = events[boundary:]

    archive_payloads = []
    for event in archived_events:
        archived = dict(event)
        archived["archived_from"] = SESSION_EVENTS_FILE
        archived["archive_boundary_index"] = boundary
        archive_payloads.append(archived)
    deleted = store.move_jsonl_records_exact(
        SESSION_EVENTS_FILE,
        SESSION_EVENTS_ARCHIVE_FILE,
        archived_events,
        archive_payloads,
    )
    pruned: dict[str, Any] = {"deleted": deleted, "scope": f"session:{session_id}" if session_id else "all_sessions"}

    receipt = persist_write_receipt(
        store,
        build_write_receipt(
            layer=LAYER_L0,
            action="workspace_archive_session_events",
            scope="memory",
            target=SESSION_EVENTS_ARCHIVE_FILE,
            target_file=f"memory/{SESSION_EVENTS_ARCHIVE_FILE}",
            session_id=session_id,
            bytes_written=sum(len(json.dumps(item, ensure_ascii=False).encode("utf-8")) for item in archive_payloads),
        ),
    )
    return {
        "workspace": config.workspace,
        "session_id": session_id,
        "archived": True,
        "archived_events": len(archived_events),
        "archived_turns": decision.archive_turns,
        "archived_tokens": decision.archive_tokens,
        "kept_events": decision.keep_events,
        "kept_turns": decision.keep_turns,
        "boundary_event_index": boundary,
        "archive_file": f"memory/{SESSION_EVENTS_ARCHIVE_FILE}",
        "prune": pruned,
        "write_receipt": receipt,
    }


def _load_session_events_for_archive(store: WorkspaceStore, *, session_id: str = "", limit: int = 5000) -> list[dict[str, Any]]:
    if session_id:
        rows = store.find_jsonl_prefer_backend(SESSION_EVENTS_FILE, lambda row: str(row.get("session_id", "") or "") == session_id, limit=limit)
    else:
        rows = store.read_jsonl_prefer_backend(SESSION_EVENTS_FILE, limit=limit)
    return [row for row in rows if isinstance(row, dict)]
