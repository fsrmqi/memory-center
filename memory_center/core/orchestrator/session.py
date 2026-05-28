from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from ..store import WorkspaceStore
from ..write_receipts import build_write_receipt, persist_write_receipt
from .common import (
    LAYER_L0,
    SESSION_EVENTS_FILE,
    SESSION_SUMMARIES_FILE,
    TOOL_WORKSPACE_LOG_SESSION_EVENT,
    _build_case_evidence_refs,
    _build_event_source_refs,
    _event_payload,
    _load_auto_sync_rules,
    _new_session_id,
    _prepare_session_event_payload,
    _score_threshold_for_sync_mode,
    _suggest_risk_points,
    _summarize_ref,
    load_context,
)


def workspace_start_session(
    workspace_file: str | Path,
    intent: str,
    session_id: str | None = None,
    metadata: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    config, store = load_context(workspace_file)
    sid = session_id or _new_session_id()
    item = {
        "session_id": sid,
        "workspace": config.workspace,
        "event_type": "session_start",
        "intent": intent,
        "payload": metadata or {},
    }
    store.append_jsonl(SESSION_EVENTS_FILE, item)
    return {
        "started": True,
        "session_id": sid,
        "workspace": config.workspace,
        "intent": intent,
        "created_at": item.get("created_at"),
    }


def workspace_log_session_event(
    workspace_file: str | Path,
    session_id: str,
    event_type: str,
    payload: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
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


def workspace_end_session(
    workspace_file: str | Path,
    session_id: str,
    outcome: str = "",
    verified_by: List[str] | None = None,
) -> Dict[str, Any]:
    config, store = load_context(workspace_file)
    workspace_log_session_event(
        workspace_file,
        session_id,
        "session_end",
        {"outcome": outcome, "verified_by": verified_by or []},
    )
    events = _session_events(store, session_id)
    summary = _build_session_summary(config.workspace, session_id, events, outcome, verified_by or [])
    store.append_jsonl(SESSION_SUMMARIES_FILE, summary)
    return {
        "ended": True,
        "session_id": session_id,
        "workspace": config.workspace,
        "summary": summary,
    }


def workspace_recent_sessions(workspace_file: str | Path, limit: int = 10) -> Dict[str, Any]:
    config, store = load_context(workspace_file)
    summaries = store.read_jsonl_via_backend(SESSION_SUMMARIES_FILE, limit=max(limit, 1)) or store.read_jsonl(SESSION_SUMMARIES_FILE, limit=max(limit, 1))
    return {
        "workspace": config.workspace,
        "recent_sessions": list(reversed(summaries[-limit:])),
    }


def workspace_session_summary(workspace_file: str | Path, session_id: str) -> Dict[str, Any]:
    config, store = load_context(workspace_file)
    summaries = store.find_jsonl_via_backend(SESSION_SUMMARIES_FILE, lambda row: row.get("session_id") == session_id, limit=1) or store.find_jsonl(SESSION_SUMMARIES_FILE, lambda row: row.get("session_id") == session_id, limit=1)
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


def workspace_suggest_case(workspace_file: str | Path, session_id: str) -> Dict[str, Any]:
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
    }


def workspace_recent_evidence(
    workspace_file: str | Path,
    task_id: str = "",
    session_id: str = "",
    limit: int = 10,
    budget: str = "medium",
    view: str = "compact",
) -> Dict[str, Any]:
    from ..timeline import timeline_query

    config, store = load_context(workspace_file)
    result = timeline_query(str(workspace_file), task_id=task_id.strip(), session_id=session_id.strip(), kinds=["session_event", "write_receipt"], limit=limit)
    evidence: List[Dict[str, Any]] = []
    for item in result.get("timeline", []):
        if item.get("kind") == "session_event":
            raw = item.get("raw", {})
            payload = raw.get("payload", {}) if isinstance(raw.get("payload"), dict) else {}
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
    from .common import _is_compact_view
    from .compact import _measure_compact_gain
    from ..tracking import log_token_gain

    if _is_compact_view(view):
        compact_evidence = _compact_evidence_entries(result["evidence"], budget=budget)
        compact_result = {**result, "evidence": compact_evidence}
        gain = _measure_compact_gain(result, compact_result)
        log_token_gain(workspace_file, "workspace_recent_evidence", budget=budget, model="", raw_tokens=gain["raw_tokens"], compact_tokens=gain["compact_tokens"], view=view)
        return compact_result
    return result


def _session_events(store: WorkspaceStore, session_id: str) -> List[Dict[str, Any]]:
    return store.find_jsonl_via_backend(SESSION_EVENTS_FILE, lambda row: row.get("session_id") == session_id, limit=1000, session_id=session_id) or store.find_jsonl(SESSION_EVENTS_FILE, lambda row: row.get("session_id") == session_id, limit=1000)


def _build_session_summary(
    workspace: str,
    session_id: str,
    events: List[Dict[str, Any]],
    outcome: str,
    verified_by: List[str],
) -> Dict[str, Any]:
    intent = ""
    for item in events:
        if item.get("event_type") == "session_start":
            intent = item.get("intent", "")
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
    return {
        "session_id": session_id,
        "workspace": workspace,
        "intent": intent,
        "event_count": len(events),
        "event_types": sorted(set(event_types)),
        "tool_calls": unique_tools,
        "projects": sorted(projects),
        "files": sorted(files)[:50],
        "outcome": outcome,
        "verified_by": verified_by,
        "summary": summary_text,
        "notable_terms": notable_terms[-10:],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _summary_text(intent: str, tool_calls: List[str], files: set[str], projects: set[str], event_types: List[str]) -> str:
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


def _build_session_overview(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    payload_ref_count = 0
    source_ref_like_count = 0
    event_types: Dict[str, int] = {}
    payload_refs: List[str] = []
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


def _compact_evidence_entries(entries: List[Dict[str, Any]], budget: str = "medium") -> List[Dict[str, Any]]:
    from .common import _budget_limits

    limits = _budget_limits(budget)
    return [
        {
            "ref_id": item.get("ref_id", ""),
            "source": item.get("source", ""),
            "summary": item.get("summary", ""),
            "created_at": item.get("created_at", ""),
            "payload_ref": item.get("payload_ref", ""),
            "receipt_ref": item.get("receipt_ref", ""),
        }
        for item in entries[: limits["events"]]
    ]