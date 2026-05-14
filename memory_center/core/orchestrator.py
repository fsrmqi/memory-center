from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

from .artifacts import (
    append_change_log,
    append_task_change_log,
    create_task_space,
    get_artifact,
    get_task_artifact,
    list_task_spaces,
    resolve_task_space,
    update_artifact,
    update_task_artifact,
)
from .config import load_workspace_config
from .registry import resolve_group
from .rules import match_rules
from .semantic import semantic_index_stats, semantic_query
from .store import WorkspaceStore

SESSION_EVENTS_FILE = "session-events.jsonl"
SESSION_SUMMARIES_FILE = "session-summaries.jsonl"


def load_context(workspace_file: str | Path):
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    return config, store


def workspace_status(workspace_file: str | Path) -> Dict[str, Any]:
    config, store = load_context(workspace_file)
    active_tasks = _active_task_summaries(workspace_file, limit=5)
    return {
        "workspace": config.workspace,
        "root": str(config.root_path),
        "services": [s.__dict__ for s in config.services],
        "index_counts": {
            "files": len(store.read_json("file-index.json", [])),
            "symbols": len(store.read_json("java-symbol-index.json", [])),
            "apis": len(store.read_json("api-index.json", [])),
            "feigns": len(store.read_json("feign-index.json", [])),
            "mq": len(store.read_json("mq-index.json", [])),
            "cases": len(store.read_jsonl("cross-service-task-memory.jsonl", limit=1000)),
            "session_events": len(store.read_jsonl(SESSION_EVENTS_FILE, limit=5000)),
            "session_summaries": len(store.read_jsonl(SESSION_SUMMARIES_FILE, limit=1000)),
            "semantic_docs": semantic_index_stats(workspace_file).get("doc_count", 0),
        },
        "semantic_index": semantic_index_stats(workspace_file),
        "active_task_spaces": active_tasks,
        "topology": store.read_json("service-topology.json", {}),
    }


def workspace_sniff(workspace_file: str | Path, intent: str, limit: int = 12) -> Dict[str, Any]:
    config, store = load_context(workspace_file)
    file_index = store.read_json("file-index.json", [])
    symbols = store.read_json("java-symbol-index.json", [])
    apis = store.read_json("api-index.json", [])
    feigns = store.read_json("feign-index.json", [])
    mq = store.read_json("mq-index.json", [])
    cases = store.read_jsonl("cross-service-task-memory.jsonl", limit=200)

    keywords = tokenize(intent)
    matched_files = rank_files(file_index, symbols, keywords)[:limit]
    matched_services = sorted({item["project"] for item in matched_files})
    related_apis = [x for x in apis if any(k in json.dumps(x, ensure_ascii=False).lower() for k in keywords)][:limit]
    related_feigns = [x for x in feigns if any(k in json.dumps(x, ensure_ascii=False).lower() for k in keywords)][:limit]
    related_mq = [x for x in mq if any(k in json.dumps(x, ensure_ascii=False).lower() for k in keywords)][:limit]
    related_cases = [x for x in cases if any(k in json.dumps(x, ensure_ascii=False).lower() for k in keywords)][-5:]
    rules = match_rules(store, intent=intent, files=[x["path"] for x in matched_files])[:10]
    sniff_risk_level = _sniff_risk_level(intent, matched_files, related_feigns, related_apis, related_mq, rules)
    task_resolution = resolve_task_space(
        workspace_file,
        intent=intent,
        create_if_missing=False,
        limit_candidates=3,
        related_texts=[item.get("task", "") for item in related_cases],
    )

    return {
        "workspace": config.workspace,
        "intent": intent,
        "risk_level": sniff_risk_level,
        "matched_services": matched_services,
        "candidate_files": matched_files,
        "related_apis": related_apis,
        "related_feigns": related_feigns,
        "related_mq": related_mq,
        "related_rules": rules,
        "historical_cases": related_cases,
        "task_candidates": task_resolution.get("candidates", []),
        "resolved_task": {key: task_resolution.get(key) for key in ["resolved", "task_id", "title", "status", "owner", "tags", "priority", "score"]},
        "symbolic_context": _build_sniff_symbolic_context(intent, sniff_risk_level, matched_services, matched_files, related_feigns, related_apis, related_mq, related_cases),
        "next_steps": [
            "先调用 memory_search_code 缩小入口范围，再用 memory_symbol 定位关键符号",
            "对关键符号调用 memory_callers / memory_callees 理清上下游调用链",
            "改动前调用 memory_plan_change 与 memory_verify_checklist，明确风险与验证项",
            "如果涉及 DTO/Feign/MQ Message，再调用 workspace_check_contract",
            "编辑前调用 workspace_check_rules，完成后调用 workspace_record_case 沉淀经验",
        ],
    }


def workspace_trace(workspace_file: str | Path, entry: str) -> Dict[str, Any]:
    _, store = load_context(workspace_file)
    topology = store.read_json("service-topology.json", {})
    apis = store.read_json("api-index.json", [])
    feigns = store.read_json("feign-index.json", [])
    mq = store.read_json("mq-index.json", [])
    entry_lower = entry.lower()
    return {
        "entry": entry,
        "matched_feign_edges": [x for x in topology.get("feign_edges", []) if entry_lower in json.dumps(x, ensure_ascii=False).lower()],
        "matched_apis": [x for x in apis if entry_lower in json.dumps(x, ensure_ascii=False).lower()],
        "matched_feigns": [x for x in feigns if entry_lower in json.dumps(x, ensure_ascii=False).lower()],
        "matched_mq": [x for x in mq if entry_lower in json.dumps(x, ensure_ascii=False).lower()],
        "topology_hint": topology,
    }


def workspace_check_contract(workspace_file: str | Path, contract_file: str, change_type: str) -> Dict[str, Any]:
    _, store = load_context(workspace_file)
    files = store.read_json("file-index.json", [])
    feigns = store.read_json("feign-index.json", [])
    mq = store.read_json("mq-index.json", [])
    basename = Path(contract_file).stem.lower()
    affected = []
    for item in files:
        text = item.get("path", "").lower()
        if basename in text or "common-api" in text or "message" in text or "dto" in text:
            affected.append(item)
    return {
        "contract_file": contract_file,
        "change_type": change_type,
        "affected_candidates": affected[:50],
        "related_feigns": [x for x in feigns if basename in json.dumps(x, ensure_ascii=False).lower()][:20],
        "related_mq": [x for x in mq if basename in json.dumps(x, ensure_ascii=False).lower()][:20],
        "rules": match_rules(store, intent=f"contract {change_type} {contract_file}", files=[contract_file], scopes=["contract", "dto", "feign", "message"]),
        "required_checks": [
            "全 workspace 搜索字段引用点",
            "确认历史 MQ 消息反序列化兼容",
            "确认 Feign 调用方请求/响应兼容",
            "新增字段提供默认值，删除字段需要灰度和兼容周期",
        ],
    }


def workspace_check_rules(workspace_file: str | Path, projects: List[str] | None, change_type: str, files: List[str] | None) -> Dict[str, Any]:
    _, store = load_context(workspace_file)
    intent = f"{change_type} {' '.join(projects or [])} {' '.join(files or [])}"
    rules = match_rules(store, intent=intent, files=files or [], scopes=[change_type])
    return {"projects": projects or [], "change_type": change_type, "files": files or [], "rules": rules}


def workspace_record_case(workspace_file: str | Path, task: str, projects: List[str], files: List[str], flow: str = "", risk_points: List[str] | None = None, verified_by: List[str] | None = None) -> Dict[str, Any]:
    _, store = load_context(workspace_file)
    item = {
        "task": task,
        "projects": projects,
        "files": files,
        "flow": flow,
        "risk_points": risk_points or [],
        "verified_by": verified_by or [],
    }
    store.append_jsonl("cross-service-task-memory.jsonl", item)
    return {"recorded": True, "case": item}


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
    item = {
        "session_id": session_id,
        "workspace": config.workspace,
        "event_type": event_type,
        "payload": payload or {},
    }
    store.append_jsonl(SESSION_EVENTS_FILE, item)
    return {
        "logged": True,
        "session_id": session_id,
        "workspace": config.workspace,
        "event_type": event_type,
        "created_at": item.get("created_at"),
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
    summaries = store.read_jsonl(SESSION_SUMMARIES_FILE, limit=max(limit, 1))
    return {
        "workspace": config.workspace,
        "recent_sessions": list(reversed(summaries[-limit:])),
    }


def workspace_session_summary(workspace_file: str | Path, session_id: str) -> Dict[str, Any]:
    config, store = load_context(workspace_file)
    summaries = store.find_jsonl(SESSION_SUMMARIES_FILE, lambda row: row.get("session_id") == session_id, limit=1)
    events = _session_events(store, session_id)
    return {
        "workspace": config.workspace,
        "session_id": session_id,
        "found": bool(summaries or events),
        "summary": summaries[-1] if summaries else None,
        "events": events[-50:],
    }


def workspace_suggest_case(workspace_file: str | Path, session_id: str) -> Dict[str, Any]:
    config, _ = load_context(workspace_file)
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
        "evidence_refs": _build_case_evidence_refs(events),
    }
    return {
        "workspace": config.workspace,
        "session_id": session_id,
        "found": True,
        "draft_case": draft,
        "hint": "确认后可直接调用 workspace_record_case / record-case 入库。",
    }


def workspace_resume_context(workspace_file: str | Path, intent: str, limit: int = 5) -> Dict[str, Any]:
    config, store = load_context(workspace_file)
    query_result = memory_query(workspace_file, intent, limit=limit)
    summaries = store.read_jsonl(SESSION_SUMMARIES_FILE, limit=500)
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
        for item in store.read_jsonl("cross-service-task-memory.jsonl", limit=300)
        if any(token in json.dumps(item, ensure_ascii=False).lower() for token in tokens)
    ][-limit:]
    return {
        "workspace": config.workspace,
        "intent": intent,
        "retrieval_summary": query_result.get("retrieval_summary", {}),
        "related_sessions": related_sessions[:limit],
        "related_cases": related_cases,
        "entrypoints": query_result.get("matches", [])[:limit],
        "suggested_context": _suggest_resume_context(intent, related_sessions[:limit], related_cases, query_result.get("matches", [])[:limit]),
    }


def workspace_sync_sniff_to_artifacts(
    workspace_file: str | Path,
    intent: str,
    limit: int = 12,
    task_id: str = "",
    title: str = "",
) -> Dict[str, Any]:
    config, _ = load_context(workspace_file)
    sniff = workspace_sniff(workspace_file, intent, limit=limit)
    resolved_task_id = task_id.strip()
    resolved_info = None
    if resolved_task_id:
        resolved_info = {"task_id": resolved_task_id, "created": False}
    else:
        resolved_info = resolve_task_space(
            workspace_file,
            intent=intent,
            title=title.strip(),
            create_if_missing=True,
            related_texts=[item.get("task", "") for item in sniff.get("historical_cases", [])],
        )
        resolved_task_id = str(resolved_info["task_id"])
    context_content = _merge_artifact_section(
        get_task_artifact(workspace_file, resolved_task_id, "context").get("content", ""),
        "Current Task Context / 当前任务上下文",
        _render_sniff_context_markdown(sniff),
    )
    plan_content = _merge_artifact_section(
        get_task_artifact(workspace_file, resolved_task_id, "plan").get("content", ""),
        "Suggested Plan / 建议执行计划",
        _render_sniff_plan_markdown(sniff),
    )
    summary_content = _render_task_current_summary_from_sniff(sniff, resolved_info or {})
    update_task_artifact(workspace_file, resolved_task_id, "context", context_content)
    update_task_artifact(workspace_file, resolved_task_id, "plan", plan_content)
    update_task_artifact(workspace_file, resolved_task_id, "current_summary", summary_content)
    return {
        "workspace": config.workspace,
        "synced": True,
        "intent": intent,
        "task_id": resolved_task_id,
        "task_resolution": resolved_info,
        "updated_artifacts": ["context", "plan", "current_summary"],
        "risk_level": sniff.get("risk_level", "unknown"),
    }


def workspace_sync_case_to_artifacts(
    workspace_file: str | Path,
    session_id: str,
    task_id: str = "",
    title: str = "",
) -> Dict[str, Any]:
    config, _ = load_context(workspace_file)
    draft = workspace_suggest_case(workspace_file, session_id)
    if not draft.get("found"):
        return {
            "workspace": config.workspace,
            "session_id": session_id,
            "synced": False,
            "updated_artifacts": [],
            "hint": draft.get("hint", "会话不存在。"),
        }
    case = draft.get("draft_case", {})
    resolved_task_id = task_id.strip()
    resolved_info = None
    if resolved_task_id:
        resolved_info = {"task_id": resolved_task_id, "created": False}
    else:
        related_texts = [ref.get("query", "") or ref.get("target", "") for ref in case.get("evidence_refs", [])]
        resolved_info = resolve_task_space(
            workspace_file,
            intent=case.get("task", ""),
            title=title.strip() or case.get("task", ""),
            create_if_missing=True,
            related_texts=related_texts,
        )
        resolved_task_id = str(resolved_info["task_id"])
    design_content = _merge_artifact_section(
        get_task_artifact(workspace_file, resolved_task_id, "design").get("content", ""),
        "Session Learnings / 会话沉淀",
        _render_case_markdown(case),
    )
    summary_content = _render_task_current_summary_from_case(case, resolved_info or {}, session_id)
    update_task_artifact(workspace_file, resolved_task_id, "design", design_content)
    update_task_artifact(workspace_file, resolved_task_id, "current_summary", summary_content)
    append_task_change_log(workspace_file, resolved_task_id, _render_change_log_entry(case, session_id))
    return {
        "workspace": config.workspace,
        "session_id": session_id,
        "synced": True,
        "task_id": resolved_task_id,
        "task_resolution": resolved_info,
        "updated_artifacts": ["design", "change_log", "current_summary"],
        "task": case.get("task", ""),
    }


def _new_session_id() -> str:
    return f"session-{uuid4().hex[:12]}"


def _active_task_summaries(workspace_file: str | Path, limit: int = 5) -> List[Dict[str, Any]]:
    tasks = list_task_spaces(workspace_file, include_archived=False).get("active_tasks", [])
    sorted_tasks = sorted(tasks, key=lambda item: (item.get("status") != "active", item.get("updated_at", "")), reverse=True)
    rows = []
    for item in sorted_tasks[:limit]:
        try:
            summary = get_task_artifact(workspace_file, str(item.get("task_id", "")), "current_summary").get("content", "")
        except Exception:
            summary = ""
        rows.append(
            {
                "task_id": item.get("task_id", ""),
                "title": item.get("title", ""),
                "status": item.get("status", ""),
                "owner": item.get("owner", ""),
                "tags": item.get("tags", []),
                "priority": item.get("priority", "medium"),
                "updated_at": item.get("updated_at", ""),
                "summary_preview": _trim_summary(summary),
            }
        )
    return rows


def _session_events(store: WorkspaceStore, session_id: str) -> List[Dict[str, Any]]:
    return store.find_jsonl(SESSION_EVENTS_FILE, lambda row: row.get("session_id") == session_id, limit=1000)


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
        payload = item.get("payload", {}) or {}
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


def _suggest_resume_context(
    intent: str,
    related_sessions: List[Dict[str, Any]],
    related_cases: List[Dict[str, Any]],
    entrypoints: List[Dict[str, Any]],
) -> List[str]:
    hints = [f"当前意图：{intent}"]
    if related_sessions:
        latest = related_sessions[0]
        hints.append(f"最近相关会话：{latest.get('summary') or latest.get('intent')}")
    if related_cases:
        latest_case = related_cases[-1]
        hints.append(f"最近相关经验：{latest_case.get('task')}")
    if entrypoints:
        top = entrypoints[0].get("node", {})
        if top.get("name"):
            hints.append(f"优先入口：{top.get('type', 'Node')} {top.get('name')}")
    return hints


def tokenize(text: str) -> List[str]:
    raw = "".join(ch.lower() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff" else " " for ch in text)
    words = [w for w in raw.split() if len(w) >= 2]
    # keep entire Chinese phrase fragments poorly but useful for mixed tasks
    for token in ["kafka", "rocketmq", "feign", "controller", "oldpubtime", "newpubtime", "es", "mongo", "redis", "nacos"]:
        if token in text.lower() and token not in words:
            words.append(token)
    return sorted(set(words))


def rank_files(file_index: List[Dict], symbols: List[Dict], keywords: List[str]) -> List[Dict]:
    symbol_by_file = {s["file"]: s for s in symbols}
    ranked = []
    for item in file_index:
        haystack = (item.get("path", "") + " " + json.dumps(symbol_by_file.get(item.get("path"), {}), ensure_ascii=False)).lower()
        score = sum(1 for k in keywords if k in haystack)
        path = item.get("path", "")
        if any(mark in path for mark in ["Consumer", "Listener", "Feign", "Controller", "Service", "Repository", "Mapper"]):
            score += 1
        if score > 0:
            ranked.append({**item, "score": score, "symbols": symbol_by_file.get(path, {})})
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked

# ---- graph-native agent context tools --------------------------------------
from .graph import GraphStore


def _graph(workspace_file: str | Path) -> GraphStore:
    _, store = load_context(workspace_file)
    return GraphStore(store.graph_db_path)


def memory_query(workspace_file: str | Path, query: str, limit: int = 20, node_types: List[str] | None = None) -> Dict[str, Any]:
    """Graph-aware hybrid-lite query.

    The first public release uses deterministic graph/name/path lookup. It is
    intentionally explainable and works without embeddings. Optional semantic
    retrieval can be added later without changing this tool shape.
    """
    config, store = load_context(workspace_file)
    graph = GraphStore(store.graph_db_path)
    exact_nodes = graph.find_nodes(query, types=node_types, limit=limit)
    if not exact_nodes:
        seen_nodes = {}
        for token in tokenize(query):
            for item in graph.find_nodes(token, types=node_types, limit=limit):
                seen_nodes[item["id"]] = item
        exact_nodes = list(seen_nodes.values())[:limit]
    semantic_hits = semantic_query(workspace_file, query, limit=max(limit * 3, 20))
    enriched_semantic_hits = []
    for hit in semantic_hits:
        node = graph.node_by_id(hit.get("node_id", ""))
        if not node:
            node = {
                "id": hit.get("node_id", ""),
                "type": hit.get("type", ""),
                "name": hit.get("name", ""),
                "project": hit.get("project", ""),
                "file_path": hit.get("file_path", ""),
            }
        enriched_semantic_hits.append({**hit, "node": node})
    semantic_hits = enriched_semantic_hits
    if node_types:
        semantic_hits = [item for item in semantic_hits if item.get("node", {}).get("type") in node_types]
    merged = _merge_workspace_query_hits(graph, query, exact_nodes, semantic_hits, limit)
    related_rules = match_rules(store, intent=query, files=[item["node"].get("file_path", "") for item in merged])[:10]
    cases = store.read_jsonl("cross-service-task-memory.jsonl", limit=200)
    related_cases = [c for c in cases if any(k in json.dumps(c, ensure_ascii=False).lower() for k in tokenize(query))][-5:]
    return {
        "workspace": config.workspace,
        "query": query,
        "matches": merged,
        "retrieval_summary": _summarize_query_matches(merged, limit),
        "progressive": _build_query_progressive_view(query, merged, semantic_hits[:limit], related_cases),
        "semantic_hits": semantic_hits[:limit],
        "related_rules": related_rules,
        "historical_cases": related_cases,
    }


def group_status(group: str, home: str | Path | None = None) -> Dict[str, Any]:
    resolved = resolve_group(group, home)
    workspaces = []
    totals = {"files": 0, "symbols": 0, "apis": 0, "feigns": 0, "mq": 0, "cases": 0}
    semantic_ready = 0
    semantic_backends: Dict[str, int] = {}
    group_data = _load_group_data(resolved["members"])
    for member in resolved["members"]:
        status = workspace_status(member["workspace_file"])
        workspaces.append(status)
        for key, value in status.get("index_counts", {}).items():
            totals[key] = totals.get(key, 0) + int(value)
        semantic = status.get("semantic_index", {})
        if semantic.get("ready"):
            semantic_ready += 1
        backend = semantic.get("backend", "unknown")
        semantic_backends[backend] = semantic_backends.get(backend, 0) + 1
    bridges = _build_group_bridges(group_data)
    return {
        "group": group,
        "workspace_count": len(workspaces),
        "missing_members": resolved["missing"],
        "index_totals": totals,
        "semantic_index": {
            "ready_workspace_count": semantic_ready,
            "workspace_count": len(workspaces),
            "doc_count": totals.get("semantic_docs", 0),
            "ready": semantic_ready == len(workspaces) if workspaces else False,
            "backends": semantic_backends,
        },
        "bridge_counts": _count_bridges(bridges),
        "bridges": bridges[:50],
        "workspaces": workspaces,
    }


def group_query(group: str, query: str, limit: int = 20, node_types: List[str] | None = None, home: str | Path | None = None) -> Dict[str, Any]:
    resolved = resolve_group(group, home)
    group_data = _load_group_data(resolved["members"])
    bridges = _build_group_bridges(group_data)
    workspace_results = []
    merged: Dict[str, Dict[str, Any]] = {}
    target_types = set()
    for member in resolved["members"]:
        result = memory_query(member["workspace_file"], query, limit=limit, node_types=node_types)
        workspace_ref = member["name"]
        workspace_name = result.get("workspace", workspace_ref)
        workspace_results.append({"workspace_ref": workspace_ref, "workspace": workspace_name, "workspace_file": member["workspace_file"], "result": result})
        for rank, item in enumerate(result.get("matches", []), start=1):
            node = item.get("node", {})
            if node.get("type"):
                target_types.add(node.get("type"))
            key = f"{workspace_ref}:{node.get('id', rank)}"
            current = merged.setdefault(
                key,
                {
                    "workspace_ref": workspace_ref,
                    "workspace": workspace_name,
                    "node": node,
                    "neighbors": item.get("neighbors", []),
                    "rrf_score": 0.0,
                    "semantic_score": 0.0,
                    "best_rank": rank,
                    "retrieval_sources": [],
                },
            )
            current["rrf_score"] += float(item.get("exact_score", _rrf(rank)))
            current["semantic_score"] = max(current["semantic_score"], float(item.get("semantic_score", 0.0)))
            current["best_rank"] = min(current["best_rank"], rank)
            if "exact" not in current["retrieval_sources"]:
                current["retrieval_sources"].append("exact")
    for entry in workspace_results:
        for hit in entry["result"].get("semantic_hits", []):
            _merge_group_semantic_hit(
                merged,
                entry["workspace_ref"],
                entry["workspace"],
                hit,
                entry["result"].get("matches", []),
                target_types,
            )
    resolved_target_types = _resolve_group_target_types(query, sorted(t for t in target_types if t))
    merged_all = sorted(merged.values(), key=lambda item: _group_query_match_key(item, resolved_target_types))
    merged_matches = merged_all[:limit]
    bridges = _sort_bridges(_filter_bridges(bridges, query, limit), resolved_target_types)
    return {
        "group": group,
        "query": query,
        "workspace_count": len(workspace_results),
        "missing_members": resolved["missing"],
        "merged_matches": merged_matches,
        "retrieval_summary": _summarize_group_query_matches(merged_all, limit),
        "progressive": _build_group_query_progressive_view(group, query, merged_matches, bridges, workspace_results, limit),
        "target_types": resolved_target_types,
        "related_bridges": bridges,
        "workspace_results": workspace_results,
    }


def group_impact(
    group: str,
    target: str,
    direction: str = "upstream",
    max_depth: int = 3,
    home: str | Path | None = None,
) -> Dict[str, Any]:
    resolved = resolve_group(group, home)
    group_data = _load_group_data(resolved["members"])
    bridges = _build_group_bridges(group_data)
    lookup = group_query(group, target, limit=8, home=home)
    workspace_impacts = []
    confirmed: List[Dict[str, Any]] = []
    probable: List[Dict[str, Any]] = []
    possible: List[Dict[str, Any]] = []
    impacted_projects = set()
    impacted_workspaces = set()
    target_types = set()

    for member in resolved["members"]:
        result = memory_impact(member["workspace_file"], target, direction=direction, max_depth=max_depth)
        workspace_impacts.append({"workspace_ref": member["name"], "workspace_file": member["workspace_file"], "impact": result})
        if not result.get("found"):
            continue
        target_types.add(result.get("target", {}).get("type", ""))
        impacted_workspaces.add(member["name"])
        impacted_projects.update(result.get("impacted_projects", []))
        for item in result.get("confirmed_impacts", []):
            confirmed.append({"workspace_ref": member["name"], "workspace": result["target"].get("project", result.get("target", {}).get("name", "")), "kind": "graph", "impact": item})
        for item in result.get("probable_impacts", []):
            probable.append({"workspace_ref": member["name"], "workspace": result["target"].get("project", result.get("target", {}).get("name", "")), "kind": "graph", "impact": item})
        for item in result.get("possible_impacts", []):
            possible.append({"workspace_ref": member["name"], "workspace": result["target"].get("project", result.get("target", {}).get("name", "")), "kind": "graph", "impact": item})

    resolved_target_types = _resolve_group_target_types(target, sorted(t for t in target_types if t))
    bridge_candidates = _filter_impact_bridges(bridges, target, resolved_target_types, limit=100)
    for bridge in bridge_candidates:
        record = {"kind": "bridge", "impact": bridge}
        impacted_workspaces.update([bridge.get("source_workspace", ""), bridge.get("target_workspace", "")])
        impacted_projects.update([bridge.get("source_project", ""), bridge.get("target_project", "")])
        confidence = float(bridge.get("confidence", 0))
        if confidence >= 0.80:
            confirmed.append(record)
        elif confidence >= 0.55:
            probable.append(record)
        else:
            possible.append(record)

    impacted_projects.discard("")
    impacted_workspaces.discard("")
    confirmed = _filter_group_impact_records(confirmed, resolved_target_types)
    probable = _filter_group_impact_records(probable, resolved_target_types)
    possible = _filter_group_impact_records(possible, resolved_target_types)
    confirmed = _sort_group_impact_records(confirmed, resolved_target_types)
    probable = _sort_group_impact_records(probable, resolved_target_types)
    possible = _sort_group_impact_records(possible, resolved_target_types)
    bridge_candidates = _sort_bridges(bridge_candidates, resolved_target_types)
    found = any(item["impact"].get("found") for item in workspace_impacts) or bool(confirmed or probable or possible)
    if confirmed or len(impacted_workspaces) >= 2:
        risk_level = "high"
    elif probable:
        risk_level = "medium"
    else:
        risk_level = "low" if found else "unknown"

    return {
        "group": group,
        "target": target,
        "direction": direction,
        "max_depth": max_depth,
        "found": found,
        "risk_level": risk_level,
        "impacted_workspaces": sorted(impacted_workspaces),
        "impacted_projects": sorted(impacted_projects),
        "confirmed_impacts": confirmed[:200],
        "probable_impacts": probable[:200],
        "possible_impacts": possible[:200],
        "lookup": _build_lookup_payload(lookup, match_key="merged_matches"),
        "evidence_summary": _build_group_impact_evidence_summary(confirmed, probable, possible, bridge_candidates),
        "progressive": _build_group_impact_progressive_view(group, target, confirmed, probable, possible, bridge_candidates, impacted_workspaces, impacted_projects),
        "target_types": resolved_target_types,
        "related_bridges": bridge_candidates[:50],
        "workspace_impacts": workspace_impacts,
        "missing_members": resolved["missing"],
        "unknown_risks": _unknown_static_analysis_risks(),
    }


def memory_context(workspace_file: str | Path, name: str, max_depth: int = 2) -> Dict[str, Any]:
    graph = _graph(workspace_file)
    lookup = memory_query(workspace_file, name, limit=8)
    matches = [item.get("node", {}) for item in lookup.get("matches", []) if item.get("node")]
    if not matches:
        return {"name": name, "found": False, "matches": [], "lookup": _build_lookup_payload(lookup)}
    node = _best_match(matches, name)
    incoming = graph.neighbors(node["id"], direction="upstream", max_depth=max_depth, limit=100)
    outgoing = graph.neighbors(node["id"], direction="downstream", max_depth=max_depth, limit=100)
    return {
        "name": name,
        "found": True,
        "node": node,
        "incoming": incoming,
        "outgoing": outgoing,
        "lookup": _build_lookup_payload(lookup),
        "evidence_summary": _build_context_evidence_summary(incoming, outgoing),
        "progressive": _build_context_progressive_view(node, incoming, outgoing),
    }


def memory_symbol(workspace_file: str | Path, name: str, limit: int = 10) -> Dict[str, Any]:
    lookup = memory_query(workspace_file, name, limit=limit, node_types=["Class", "Method", "Field", "FeignClient", "FeignMethod", "Endpoint", "MQTopic", "MQConsumer", "ConfigKey", "File"])
    matches = [item.get("node", {}) for item in lookup.get("matches", []) if item.get("node")]
    if not matches:
        return {"name": name, "found": False, "matches": [], "lookup": _build_lookup_payload(lookup)}
    best = _best_match(matches, name)
    return {
        "name": name,
        "found": True,
        "best_match": best,
        "matches": lookup.get("matches", [])[:limit],
        "lookup": _build_lookup_payload(lookup),
    }


def memory_callers(workspace_file: str | Path, symbol: str, depth: int = 2, limit: int = 80) -> Dict[str, Any]:
    graph = _graph(workspace_file)
    info = memory_symbol(workspace_file, symbol, limit=8)
    if not info.get("found"):
        return {"symbol": symbol, "found": False, "callers": [], "lookup": info.get("lookup", {})}
    node = info["best_match"]
    edges = graph.neighbors(node["id"], direction="upstream", max_depth=depth, limit=max(limit, 20))
    callers = _filter_call_edges(edges, direction="upstream")[:limit]
    return {
        "symbol": symbol,
        "found": True,
        "target": node,
        "depth": depth,
        "callers": callers,
        "lookup": info.get("lookup", {}),
    }


def memory_callees(workspace_file: str | Path, symbol: str, depth: int = 2, limit: int = 80) -> Dict[str, Any]:
    graph = _graph(workspace_file)
    info = memory_symbol(workspace_file, symbol, limit=8)
    if not info.get("found"):
        return {"symbol": symbol, "found": False, "callees": [], "lookup": info.get("lookup", {})}
    node = info["best_match"]
    edges = graph.neighbors(node["id"], direction="downstream", max_depth=depth, limit=max(limit, 20))
    callees = _filter_call_edges(edges, direction="downstream")[:limit]
    return {
        "symbol": symbol,
        "found": True,
        "target": node,
        "depth": depth,
        "callees": callees,
        "lookup": info.get("lookup", {}),
    }


def memory_search_code(workspace_file: str | Path, query: str, scope: str = "", limit: int = 20) -> Dict[str, Any]:
    config, store = load_context(workspace_file)
    keywords = tokenize(query)
    files = store.read_json("file-index.json", [])
    symbols = store.read_json("java-symbol-index.json", [])
    symbol_map = {item.get("file", ""): item for item in symbols}
    scope_l = scope.lower().strip()
    hits: List[Dict[str, Any]] = []
    for item in files:
        path = item.get("path", "")
        if scope_l and scope_l not in path.lower():
            continue
        text = f"{path} {item.get('project', '')} {item.get('service_name', '')}".lower()
        symbol_item = symbol_map.get(path, {})
        symbol_text = json.dumps(symbol_item, ensure_ascii=False).lower()
        score = sum(1 for token in keywords if token in text or token in symbol_text)
        if score <= 0:
            continue
        hits.append(
            {
                "project": item.get("project", ""),
                "service_name": item.get("service_name", ""),
                "path": path,
                "score": score,
                "symbol_count": int(symbol_item.get("class_count", 0)) + int(symbol_item.get("method_count", 0)) + int(symbol_item.get("field_count", 0)),
                "suffix": item.get("suffix", ""),
            }
        )
    hits.sort(key=lambda row: (-int(row.get("score", 0)), -int(row.get("symbol_count", 0)), row.get("path", "")))
    return {
        "workspace": config.workspace,
        "query": query,
        "scope": scope,
        "hits": hits[:limit],
        "total_hits": len(hits),
        "progressive": _build_search_progressive_view(query, scope, hits[:limit]),
        "tips": [
            "命中后可继续调用 memory_symbol / memory_context 深挖。",
            "改动前建议调用 memory_impact 和 workspace_check_rules。",
        ],
    }


def memory_plan_change(workspace_file: str | Path, target: str, direction: str = "upstream", max_depth: int = 3) -> Dict[str, Any]:
    impact = memory_impact(workspace_file, target, direction=direction, max_depth=max_depth)
    if not impact.get("found"):
        return {
            "target": target,
            "found": False,
            "plan": [],
            "hint": "未找到目标节点，先用 memory_search_code / memory_symbol 定位。",
            "impact": impact,
        }
    plan = [
        "1) 先确认目标节点与影响范围（context + impact）。",
        "2) 优先处理 high confidence 影响点，再处理 probable/possible。",
        "3) 执行契约兼容检查（DTO/Feign/MQ/Config）。",
        "4) 增量改动并同步补测试，执行回归与静态检查。",
        "5) 完成后记录 case，沉淀流程与风险点。",
    ]
    return {
        "target": impact.get("target", {}),
        "found": True,
        "risk_level": impact.get("risk_level", "unknown"),
        "plan": plan,
        "required_rules": impact.get("required_rules", []),
        "review_checklist": impact.get("review_checklist", []),
        "impact": {
            "confirmed_count": len(impact.get("confirmed_impacts", [])),
            "probable_count": len(impact.get("probable_impacts", [])),
            "possible_count": len(impact.get("possible_impacts", [])),
            "impacted_projects": impact.get("impacted_projects", []),
        },
    }


def memory_verify_checklist(workspace_file: str | Path, target: str) -> Dict[str, Any]:
    impact = memory_impact(workspace_file, target, direction="upstream", max_depth=3)
    checklist = list(impact.get("review_checklist", []))
    target_type = (impact.get("target", {}) or {}).get("type", "")
    if target_type in {"FeignClient", "FeignMethod", "Endpoint"}:
        checklist.extend(
            [
                "校验调用方与被调方请求/响应结构兼容。",
                "校验 HTTP 状态码与错误码约定是否一致。",
            ]
        )
    if target_type in {"MQTopic", "MQConsumer"}:
        checklist.extend(
            [
                "校验消息 schema 向后兼容与默认值策略。",
                "校验消费幂等、重试与死信处理。",
            ]
        )
    if target_type in {"ConfigKey"}:
        checklist.extend(
            [
                "校验默认配置和环境覆盖是否一致。",
                "校验灰度发布期间新旧配置都可工作。",
            ]
        )
    deduped = list(dict.fromkeys(checklist))
    return {
        "target": target,
        "found": impact.get("found", False),
        "risk_level": impact.get("risk_level", "unknown"),
        "target_type": target_type,
        "checklist": deduped,
        "required_rules": impact.get("required_rules", []),
    }


def memory_impact(workspace_file: str | Path, target: str, direction: str = "upstream", max_depth: int = 3) -> Dict[str, Any]:
    """Evidence-based impact analysis.

    Impacts are intentionally split into confirmed/probable/possible buckets so
    AI agents do not treat weak static-analysis hints as exact compiler truth.
    """
    _, store = load_context(workspace_file)
    graph = GraphStore(store.graph_db_path)
    lookup = memory_query(workspace_file, target, limit=8)
    matches = [item.get("node", {}) for item in lookup.get("matches", []) if item.get("node")]
    if not matches:
        return {
            "target": target,
            "found": False,
            "risk_level": "unknown",
            "confirmed_impacts": [],
            "probable_impacts": [],
            "possible_impacts": [],
            "lookup": _build_lookup_payload(lookup),
            "progressive": _build_impact_progressive_view(target, None, [], [], []),
            "unknown_risks": _unknown_static_analysis_risks(),
        }
    node = _best_match(matches, target)
    impacts = graph.neighbors(node["id"], direction=direction, max_depth=max_depth, limit=300)
    confirmed = [x for x in impacts if float(x.get("confidence", 0)) >= 0.80]
    probable = [x for x in impacts if 0.55 <= float(x.get("confidence", 0)) < 0.80]
    possible = [x for x in impacts if float(x.get("confidence", 0)) < 0.55]
    impacted_projects = sorted(
        {x.get("source", {}).get("project") for x in impacts if x.get("source", {}).get("project")}
        | {x.get("target", {}).get("project") for x in impacts if x.get("target", {}).get("project")}
    )
    risky_types = {"DTO", "Field", "FeignClient", "FeignMethod", "MQTopic", "MQConsumer", "Endpoint", "ConfigKey"}
    if node["type"] in risky_types or len(impacted_projects) >= 3 or confirmed:
        risk_level = "high" if node["type"] in risky_types or len(impacted_projects) >= 3 else "medium"
    else:
        risk_level = "low" if impacts else "unknown"
    rules = match_rules(store, intent=f"impact {target} {node['type']}", files=[node.get("file_path", "")])[:12]
    return {
        "target": node,
        "found": True,
        "direction": direction,
        "max_depth": max_depth,
        "risk_level": risk_level,
        "impacted_projects": impacted_projects,
        "confirmed_impacts": confirmed,
        "probable_impacts": probable,
        "possible_impacts": possible,
        "lookup": _build_lookup_payload(lookup),
        "evidence_summary": _build_impact_evidence_summary(confirmed, probable, possible),
        "progressive": _build_impact_progressive_view(target, node, confirmed, probable, possible),
        "required_rules": rules,
        "review_checklist": _impact_checklist(node, risk_level),
        "unknown_risks": _unknown_static_analysis_risks(),
        "explanation": {
            "confirmed": "confidence >= 0.80, usually direct declarations, annotations, config, or contract edges",
            "probable": "0.55 <= confidence < 0.80, usually import, Feign endpoint match, inferred method/field usage",
            "possible": "confidence < 0.55, weak hints only; verify manually",
        },
    }


def memory_contracts(workspace_file: str | Path) -> Dict[str, Any]:
    _, store = load_context(workspace_file)
    return {
        "feign_contracts": store.read_json("feign-index.json", []),
        "mq_contracts": store.read_json("mq-index.json", []),
        "api_contracts": store.read_json("api-index.json", []),
        "rules": match_rules(store, intent="contract feign dto message api", scopes=["contract", "dto", "feign", "message"]),
    }


def memory_detect_changes(workspace_file: str | Path, scope: str = "staged") -> Dict[str, Any]:
    """Map local git changes to graph nodes and rules.

    This is a conservative pre-review signal, not a replacement for tests or code review.
    """
    import subprocess

    config, store = load_context(workspace_file)
    graph = GraphStore(store.graph_db_path)
    changed: List[str] = []
    for svc in config.services:
        repo = config.root_path / svc.path
        if not (repo / ".git").exists():
            continue
        cmd = ["git", "diff", "--name-only"]
        if scope == "staged":
            cmd = ["git", "diff", "--name-only", "--cached"]
        elif scope == "head":
            cmd = ["git", "diff", "--name-only", "HEAD~1..HEAD"]
        try:
            out = subprocess.check_output(cmd, cwd=repo, text=True, stderr=subprocess.DEVNULL)
            changed.extend([f"{svc.path}/{line.strip()}" for line in out.splitlines() if line.strip()])
        except Exception:
            continue
    file_index = store.read_json("file-index.json", [])
    matched_files = [f for f in file_index if f.get("path") in changed]
    changed_text = " ".join(changed)
    rules = match_rules(store, intent=f"git changes {changed_text}", files=changed)[:20]
    affected_projects = sorted({f.get("project") for f in matched_files})
    graph_hits = []
    for file in changed[:50]:
        graph_hits.extend(graph.find_nodes(file, types=["File"], limit=5))
    confirmed_edges = []
    for hit in graph_hits[:20]:
        confirmed_edges.extend(graph.neighbors(hit["id"], direction="both", max_depth=1, limit=20))
    high_markers = ["common-api", "Feign", "Message", "Consumer", "Controller", "DTO", "application.yml", "bootstrap.yml"]
    risk_level = "high" if any(m in changed_text for m in high_markers) or any(e.get("type") in {"IMPLEMENTS_FEIGN", "CONSUMES_TOPIC", "READS_FIELD"} for e in confirmed_edges) else "medium" if changed else "low"
    return {
        "scope": scope,
        "changed_files": changed,
        "matched_index_files": matched_files,
        "affected_projects": affected_projects,
        "risk_level": risk_level,
        "graph_evidence": confirmed_edges[:50],
        "rules": rules,
        "review_checklist": [
            "检查公共 DTO / Feign / MQ Message 是否存在兼容性风险",
            "检查 Kafka/RocketMQ 消费是否幂等、可重试、可观测",
            "检查 ES/Mongo/DB 写入是否具备失败明细与补偿策略",
            "检查日志是否包含 chainId、siteCode、uid、业务主键",
            "如果 graph_evidence 为空，不代表无影响；可能是索引精度不足或尚未 reindex",
        ],
        "unknown_risks": _unknown_static_analysis_risks(),
    }



def _best_match(matches: List[Dict[str, Any]], query: str = "") -> Dict[str, Any]:
    q = (query or "").lower()
    priority = {
        "Class": 0,
        "FeignClient": 1,
        "FeignMethod": 2,
        "Method": 3,
        "Field": 4,
        "Endpoint": 5,
        "MQTopic": 6,
        "MQConsumer": 7,
        "ConfigKey": 8,
        "File": 20,
    }

    def key(item: Dict[str, Any]):
        name = (item.get("name") or "").lower()
        exact = 0 if name == q or name.endswith("." + q) else 1
        return (exact, priority.get(item.get("type"), 10), len(item.get("id", "")))

    return sorted(matches, key=key)[0]


def _event_payload(event: Dict[str, Any]) -> Dict[str, Any]:
    payload = event.get("payload", {})
    return payload if isinstance(payload, dict) else {}


def _build_case_evidence_refs(events: List[Dict[str, Any]], limit: int = 12) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    for idx, event in enumerate(events[-limit:], start=max(len(events) - limit, 0) + 1):
        payload = _event_payload(event)
        ref = {
            "event_index": idx,
            "event_type": event.get("event_type", ""),
            "created_at": event.get("created_at", ""),
        }
        for key in ["tool_name", "query", "target", "name", "project", "file_path", "path"]:
            value = payload.get(key)
            if isinstance(value, str) and value:
                ref[key] = value
        refs.append(ref)
    return refs


def _merge_artifact_section(existing: str, section_title: str, body: str) -> str:
    marker = f"## {section_title}"
    if marker in existing:
        prefix = existing.split(marker, 1)[0].rstrip()
        return f"{prefix}\n\n{marker}\n\n{body.strip()}\n"
    suffix = f"\n\n{marker}\n\n{body.strip()}\n"
    return existing.rstrip() + suffix if existing.strip() else f"{marker}\n\n{body.strip()}\n"


def _render_sniff_context_markdown(sniff: Dict[str, Any]) -> str:
    lines = [
        f"- Intent: {sniff.get('intent', '')}",
        f"- Risk level: {sniff.get('risk_level', 'unknown')}",
        "",
        "### Focus Services",
    ]
    lines.extend([f"- {item}" for item in sniff.get("matched_services", [])[:6]] or ["- None"])
    lines.append("")
    lines.append("### Candidate Files")
    lines.extend([f"- {item.get('path', '')}" for item in sniff.get("candidate_files", [])[:8]] or ["- None"])
    return "\n".join(lines)


def _render_sniff_plan_markdown(sniff: Dict[str, Any]) -> str:
    lines = [
        f"- Intent: {sniff.get('intent', '')}",
        "",
        "### Next Steps",
    ]
    lines.extend([f"- {item}" for item in sniff.get("next_steps", [])] or ["- None"])
    return "\n".join(lines)


def _render_case_markdown(case: Dict[str, Any]) -> str:
    lines = [
        f"- Task: {case.get('task', '')}",
        f"- Projects: {', '.join(case.get('projects', []))}",
        f"- Flow: {case.get('flow', '')}",
        "",
        "### Risk Points",
    ]
    lines.extend([f"- {item}" for item in case.get("risk_points", [])] or ["- None"])
    lines.append("")
    lines.append("### Evidence Refs")
    lines.extend(
        [
            f"- [{item.get('event_type', '')}] {item.get('tool_name', '') or item.get('query', '') or item.get('target', '')}"
            for item in case.get("evidence_refs", [])[:10]
        ]
        or ["- None"]
    )
    return "\n".join(lines)


def _render_change_log_entry(case: Dict[str, Any], session_id: str) -> str:
    risk_points = ", ".join(case.get("risk_points", [])[:4])
    return (
        f"Session `{session_id}` synced into shared artifacts.\n\n"
        f"- Task: {case.get('task', '')}\n"
        f"- Projects: {', '.join(case.get('projects', []))}\n"
        f"- Risk points: {risk_points or 'None'}"
    )


def _render_task_current_summary_from_sniff(sniff: Dict[str, Any], resolved_info: Dict[str, Any]) -> str:
    services = ", ".join(sniff.get("matched_services", [])[:4]) or "None"
    top_files = ", ".join(item.get("path", "") for item in sniff.get("candidate_files", [])[:3]) or "None"
    next_steps = "\n".join(f"- {item}" for item in sniff.get("next_steps", [])[:4])
    return (
        "# Current Summary / 当前最短上下文\n\n"
        f"- Intent: {sniff.get('intent', '')}\n"
        f"- Risk level: {sniff.get('risk_level', 'unknown')}\n"
        f"- Resolved task: {resolved_info.get('title', resolved_info.get('task_id', ''))}\n"
        f"- Services: {services}\n"
        f"- Top files: {top_files}\n\n"
        "## Next Steps\n\n"
        f"{next_steps}\n"
    )


def _render_task_current_summary_from_case(case: Dict[str, Any], resolved_info: Dict[str, Any], session_id: str) -> str:
    risk_points = ", ".join(case.get("risk_points", [])[:4]) or "None"
    projects = ", ".join(case.get("projects", [])[:6]) or "None"
    return (
        "# Current Summary / 当前最短上下文\n\n"
        f"- Task: {case.get('task', '')}\n"
        f"- Session: {session_id}\n"
        f"- Resolved task: {resolved_info.get('title', resolved_info.get('task_id', ''))}\n"
        f"- Projects: {projects}\n"
        f"- Flow: {case.get('flow', '')}\n"
        f"- Risk points: {risk_points}\n"
    )


def _trim_summary(text: str, limit: int = 220) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def _build_sniff_symbolic_context(
    intent: str,
    risk_level: str,
    matched_services: List[str],
    matched_files: List[Dict[str, Any]],
    related_feigns: List[Dict[str, Any]],
    related_apis: List[Dict[str, Any]],
    related_mq: List[Dict[str, Any]],
    related_cases: List[Dict[str, Any]],
) -> Dict[str, Any]:
    service_nodes = [item for item in matched_services[:4] if item]
    file_nodes = [Path(item.get("path", "")).name for item in matched_files[:4] if item.get("path")]
    feign_nodes = [item.get("interface", "") for item in related_feigns[:3] if item.get("interface")]
    api_nodes = [f"{item.get('http_method', '')} {item.get('path', '')}".strip() for item in related_apis[:3] if item.get("path")]
    mq_nodes = [item.get("topic", "") for item in related_mq[:3] if item.get("topic")]
    case_nodes = [item.get("task", "") for item in related_cases[-2:] if item.get("task")]
    lines = ["flowchart LR", '  I["Intent"]']
    for idx, service in enumerate(service_nodes, start=1):
        node_id = f"S{idx}"
        lines.append(f'  {node_id}["Service: {service}"]')
        lines.append(f"  I --> {node_id}")
    for idx, name in enumerate(file_nodes, start=1):
        node_id = f"F{idx}"
        lines.append(f'  {node_id}["File: {name}"]')
        lines.append(f"  I --> {node_id}")
    for idx, name in enumerate(feign_nodes, start=1):
        node_id = f"G{idx}"
        lines.append(f'  {node_id}["Feign: {name}"]')
        lines.append(f"  I --> {node_id}")
    for idx, name in enumerate(api_nodes, start=1):
        node_id = f"A{idx}"
        lines.append(f'  {node_id}["API: {name}"]')
        lines.append(f"  I --> {node_id}")
    for idx, name in enumerate(mq_nodes, start=1):
        node_id = f"M{idx}"
        lines.append(f'  {node_id}["MQ: {name}"]')
        lines.append(f"  I --> {node_id}")
    for idx, name in enumerate(case_nodes, start=1):
        node_id = f"C{idx}"
        lines.append(f'  {node_id}["Case: {name}"]')
        lines.append(f"  I -.-> {node_id}")
    has_contract = bool(feign_nodes or api_nodes)
    has_mq = bool(mq_nodes)
    has_cases = bool(case_nodes)
    has_config = any(token in intent.lower() for token in ["config", "nacos", "bootstrap", "application.yml", "application.yaml"])
    flow_lines = [
        "flowchart TD",
        '  T["Task Intent"] --> S["memory_search_code"]',
        '  S --> Y["memory_symbol"]',
        '  Y --> C["memory_callers / memory_callees"]',
    ]
    if risk_level == "high":
        flow_lines.extend(
            [
                '  C --> I["memory_impact"]',
                '  I --> P["memory_plan_change"]',
                '  P --> V["memory_verify_checklist"]',
            ]
        )
    elif risk_level == "medium":
        flow_lines.extend(
            [
                '  C --> P["memory_plan_change"]',
                '  P --> V["memory_verify_checklist"]',
            ]
        )
    else:
        flow_lines.append('  C --> V["memory_verify_checklist"]')
    if has_contract:
        flow_lines.append(f'  {"P" if risk_level != "low" else "V"} --> K["workspace_check_contract (Feign/API)"]')
        flow_lines.append('  K --> R["workspace_check_rules"]')
    if has_mq:
        flow_lines.append(f'  {"P" if risk_level != "low" else "V"} --> M["MQ compatibility review"]')
        flow_lines.append('  M --> R["workspace_check_rules"]')
    if has_config:
        flow_lines.append(f'  {"P" if risk_level != "low" else "V"} --> G["Config diff review"]')
        flow_lines.append('  G --> R["workspace_check_rules"]')
    if not (has_contract or has_mq or has_config):
        flow_lines.append(f'  {"P" if risk_level != "low" else "V"} --> R["workspace_check_rules"]')
    if has_cases:
        flow_lines.append('  R --> H["Review historical cases"]')
        flow_lines.append('  H --> E["Edit & Test"]')
    else:
        flow_lines.append('  R --> E["Edit & Test"]')
    flow_lines.append('  E --> W["workspace_record_case"]')
    return {
        "intent": intent,
        "focus_entities": {
            "services": service_nodes,
            "files": file_nodes,
            "feigns": feign_nodes,
            "apis": api_nodes,
            "mq_topics": mq_nodes,
            "cases": case_nodes,
        },
        "mermaid": "\n".join(lines),
        "entities_mermaid": "\n".join(lines),
        "flow_mermaid": "\n".join(flow_lines),
        "flow_flags": {
            "risk_level": risk_level,
            "has_contract": has_contract,
            "has_mq": has_mq,
            "has_config": has_config,
            "has_cases": has_cases,
        },
    }


def _build_progressive_levels(summary: Dict[str, Any], evidence: Dict[str, Any], detail: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "level": "summary-evidence-detail",
        "summary": summary,
        "evidence": evidence,
        "detail": detail,
    }


def _sniff_risk_level(
    intent: str,
    matched_files: List[Dict[str, Any]],
    related_feigns: List[Dict[str, Any]],
    related_apis: List[Dict[str, Any]],
    related_mq: List[Dict[str, Any]],
    rules: List[Dict[str, Any]],
) -> str:
    text = intent.lower()
    paths = " ".join(item.get("path", "").lower() for item in matched_files)
    must_rules = sum(1 for item in rules if item.get("severity") == "must")
    if related_feigns or related_apis or related_mq:
        return "high"
    if any(token in text for token in ["dto", "feign", "mq", "message", "contract", "topic", "config"]):
        return "high"
    if any(token in paths for token in ["feign", "controller", "consumer", "message", "dto", "config"]):
        return "high"
    if must_rules >= 2:
        return "medium"
    return "low"


def _build_search_progressive_view(query: str, scope: str, hits: List[Dict[str, Any]]) -> Dict[str, Any]:
    return _build_progressive_levels(
        {
            "query": query,
            "scope": scope,
            "top_hit_count": len(hits),
            "top_paths": [item.get("path", "") for item in hits[:3]],
        },
        {
            "top_projects": sorted({item.get("project", "") for item in hits[:5] if item.get("project")}),
            "scored_hits": [{"path": item.get("path", ""), "score": item.get("score", 0)} for item in hits[:5]],
        },
        {
            "next_action": "对 top_paths 调用 memory_symbol / memory_context 深挖。",
            "full_paths": [item.get("path", "") for item in hits],
        },
    )


def _build_query_progressive_view(query: str, matches: List[Dict[str, Any]], semantic_hits: List[Dict[str, Any]], related_cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    top_nodes = [item.get("node", {}) for item in matches[:3]]
    return _build_progressive_levels(
        {
            "query": query,
            "top_nodes": [f"{item.get('type', '')}:{item.get('name', '')}" for item in top_nodes if item.get("name")],
            "top_sources": [item.get("retrieval_sources", []) for item in matches[:3]],
        },
        {
            "entrypoints": [
                {
                    "id": item.get("node", {}).get("id", ""),
                    "type": item.get("node", {}).get("type", ""),
                    "name": item.get("node", {}).get("name", ""),
                    "exact_score": item.get("exact_score", 0.0),
                    "semantic_score": item.get("semantic_score", 0.0),
                }
                for item in matches[:5]
            ],
            "semantic_candidates": [
                {
                    "node_id": item.get("node_id", ""),
                    "name": item.get("node", {}).get("name", ""),
                    "score": item.get("score", 0.0),
                }
                for item in semantic_hits[:5]
            ],
        },
        {
            "neighbor_preview": {
                item.get("node", {}).get("name", ""): [edge.get("type", "") for edge in item.get("neighbors", [])[:4]]
                for item in matches[:3]
            },
            "related_case_tasks": [item.get("task", "") for item in related_cases[-3:]],
        },
    )


def _build_context_progressive_view(node: Dict[str, Any], incoming: List[Dict[str, Any]], outgoing: List[Dict[str, Any]]) -> Dict[str, Any]:
    return _build_progressive_levels(
        {
            "node": f"{node.get('type', '')}:{node.get('name', '')}",
            "incoming_count": len(incoming),
            "outgoing_count": len(outgoing),
        },
        {
            "incoming_edge_types": sorted({item.get("type", "") for item in incoming if item.get("type")}),
            "outgoing_edge_types": sorted({item.get("type", "") for item in outgoing if item.get("type")}),
            "high_confidence_edges": [
                item.get("type", "")
                for item in (incoming + outgoing)
                if float(item.get("confidence", 0.0)) >= 0.80
            ][:8],
        },
        {
            "incoming_preview": [f"{item.get('source', {}).get('name', '')} -> {item.get('type', '')}" for item in incoming[:8]],
            "outgoing_preview": [f"{item.get('type', '')} -> {item.get('target', {}).get('name', '')}" for item in outgoing[:8]],
        },
    )


def _build_impact_progressive_view(
    target: str,
    node: Dict[str, Any] | None,
    confirmed: List[Dict[str, Any]],
    probable: List[Dict[str, Any]],
    possible: List[Dict[str, Any]],
) -> Dict[str, Any]:
    node_label = target if not node else f"{node.get('type', '')}:{node.get('name', '')}"
    return _build_progressive_levels(
        {
            "target": node_label,
            "confirmed_count": len(confirmed),
            "probable_count": len(probable),
            "possible_count": len(possible),
        },
        {
            "confirmed_edge_types": sorted({item.get("type", "") for item in confirmed if item.get("type")}),
            "probable_edge_types": sorted({item.get("type", "") for item in probable if item.get("type")}),
            "top_confirmed": [
                f"{item.get('type', '')}:{item.get('source', {}).get('name', '')}->{item.get('target', {}).get('name', '')}"
                for item in confirmed[:5]
            ],
        },
        {
            "probable_preview": [
                f"{item.get('type', '')}:{item.get('source', {}).get('name', '')}->{item.get('target', {}).get('name', '')}"
                for item in probable[:5]
            ],
            "possible_preview": [
                f"{item.get('type', '')}:{item.get('source', {}).get('name', '')}->{item.get('target', {}).get('name', '')}"
                for item in possible[:5]
            ],
        },
    )


def _build_group_query_progressive_view(
    group: str,
    query: str,
    merged_matches: List[Dict[str, Any]],
    bridges: List[Dict[str, Any]],
    workspace_results: List[Dict[str, Any]],
    limit: int,
) -> Dict[str, Any]:
    top_nodes = [item.get("node", {}) for item in merged_matches[:3]]
    return _build_progressive_levels(
        {
            "group": group,
            "query": query,
            "workspace_count": len(workspace_results),
            "top_nodes": [f"{item.get('type', '')}:{item.get('name', '')}" for item in top_nodes if item.get("name")],
        },
        {
            "entrypoints": [
                {
                    "workspace_ref": item.get("workspace_ref", ""),
                    "type": item.get("node", {}).get("type", ""),
                    "name": item.get("node", {}).get("name", ""),
                    "retrieval_sources": item.get("retrieval_sources", []),
                    "rrf_score": item.get("rrf_score", 0.0),
                    "semantic_score": item.get("semantic_score", 0.0),
                }
                for item in merged_matches[: min(limit, 5)]
            ],
            "bridge_preview": [
                {
                    "type": item.get("type", ""),
                    "summary": item.get("summary", ""),
                    "confidence": item.get("confidence", 0.0),
                }
                for item in bridges[:5]
            ],
        },
        {
            "workspace_breakdown": [
                {
                    "workspace_ref": item.get("workspace_ref", ""),
                    "workspace": item.get("workspace", ""),
                    "top_match_count": len(item.get("result", {}).get("matches", [])),
                    "retrieval_summary": item.get("result", {}).get("retrieval_summary", {}),
                }
                for item in workspace_results
            ],
            "neighbor_preview": {
                item.get("node", {}).get("name", ""): [edge.get("type", "") for edge in item.get("neighbors", [])[:4]]
                for item in merged_matches[:3]
            },
        },
    )


def _build_group_impact_progressive_view(
    group: str,
    target: str,
    confirmed: List[Dict[str, Any]],
    probable: List[Dict[str, Any]],
    possible: List[Dict[str, Any]],
    bridges: List[Dict[str, Any]],
    impacted_workspaces: set[str],
    impacted_projects: set[str],
) -> Dict[str, Any]:
    return _build_progressive_levels(
        {
            "group": group,
            "target": target,
            "impacted_workspace_count": len(impacted_workspaces),
            "impacted_project_count": len(impacted_projects),
            "confirmed_count": len(confirmed),
            "probable_count": len(probable),
            "possible_count": len(possible),
        },
        {
            "bridge_types": sorted({item.get("type", "") for item in bridges if item.get("type")}),
            "top_bridges": [
                {
                    "type": item.get("type", ""),
                    "summary": item.get("summary", ""),
                    "confidence": item.get("confidence", 0.0),
                }
                for item in bridges[:5]
            ],
            "top_confirmed": [
                _group_impact_record_label(item)
                for item in confirmed[:5]
            ],
        },
        {
            "confirmed_preview": [_group_impact_record_label(item) for item in confirmed[:8]],
            "probable_preview": [_group_impact_record_label(item) for item in probable[:8]],
            "possible_preview": [_group_impact_record_label(item) for item in possible[:8]],
            "impacted_workspaces": sorted(impacted_workspaces),
            "impacted_projects": sorted(impacted_projects),
        },
    )


def _group_impact_record_label(item: Dict[str, Any]) -> str:
    impact = item.get("impact", {}) if isinstance(item, dict) else {}
    if item.get("kind") == "bridge":
        return f"{impact.get('type', '')}:{impact.get('summary', '')}"
    return f"{impact.get('type', '')}:{impact.get('source', {}).get('name', '')}->{impact.get('target', {}).get('name', '')}"


def _suggest_risk_points(summary: Dict[str, Any], events: List[Dict[str, Any]]) -> List[str]:
    text = json.dumps(summary, ensure_ascii=False).lower()
    for event in events:
        text += " " + json.dumps(_event_payload(event), ensure_ascii=False).lower()
    points: List[str] = []
    if any(token in text for token in ["feign", "endpoint", "controller"]):
        points.append("Feign/API 契约兼容性")
    if any(token in text for token in ["kafka", "rocketmq", "topic", "consumer"]):
        points.append("MQ 消息兼容与消费幂等")
    if any(token in text for token in ["config", "bootstrap", "application.yml", "nacos"]):
        points.append("配置键变更与环境一致性")
    if any(token in text for token in ["dto", "field", "request", "response"]):
        points.append("DTO 字段变更兼容性")
    if not points:
        points.append("跨服务影响面复核")
    return points


def _filter_call_edges(edges: List[Dict[str, Any]], direction: str) -> List[Dict[str, Any]]:
    preferred = {
        "CALLS_METHOD",
        "CALLS_SERVICE",
        "IMPLEMENTS_FEIGN",
        "HANDLES_ENDPOINT",
        "CONSUMES_TOPIC",
        "READS_FIELD",
        "READS_CONFIG",
        "INJECTS_BEAN",
        "IMPORTS",
    }
    filtered = [item for item in edges if item.get("type") in preferred]
    filtered.sort(
        key=lambda item: (
            -float(item.get("confidence", 0.0)),
            int(item.get("depth", 99)),
            item.get("type", ""),
        )
    )
    if direction == "upstream":
        return filtered
    return filtered


def _rrf(rank: int, k: int = 60) -> float:
    return 1.0 / (k + rank)


def _merge_workspace_query_hits(
    graph: GraphStore,
    query: str,
    exact_nodes: List[Dict[str, Any]],
    semantic_hits: List[Dict[str, Any]],
    limit: int,
) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    target_types = set()

    for rank, node in enumerate(exact_nodes, start=1):
        node_id = node.get("id")
        if not node_id:
            continue
        target_types.add(node.get("type", ""))
        item = merged.setdefault(
            node_id,
            {
                "node": node,
                "neighbors": graph.neighbors(node_id, direction="both", max_depth=1, limit=20),
                "exact_score": 0.0,
                "semantic_score": 0.0,
                "best_rank": rank,
                "retrieval_sources": [],
            },
        )
        item["exact_score"] += _rrf(rank)
        item["best_rank"] = min(item["best_rank"], rank)
        if "exact" not in item["retrieval_sources"]:
            item["retrieval_sources"].append("exact")

    for semantic_rank, hit in enumerate(semantic_hits, start=1):
        node_id = hit.get("node_id")
        if not node_id:
            continue
        node = graph.node_by_id(node_id)
        if not node:
            continue
        target_types.add(node.get("type", ""))
        item = merged.setdefault(
            node_id,
            {
                "node": node,
                "neighbors": graph.neighbors(node_id, direction="both", max_depth=1, limit=20),
                "exact_score": 0.0,
                "semantic_score": 0.0,
                "best_rank": semantic_rank + 1000,
                "retrieval_sources": [],
            },
        )
        item["semantic_score"] = max(item["semantic_score"], float(hit.get("score", 0.0)))
        if "semantic" not in item["retrieval_sources"]:
            item["retrieval_sources"].append("semantic")

    resolved_target_types = _resolve_group_target_types(query, sorted(t for t in target_types if t))
    matches = list(merged.values())
    matches.sort(key=lambda item: _workspace_query_match_key(item, resolved_target_types))
    return matches[:limit]


def _workspace_query_match_key(item: Dict[str, Any], target_types: List[str]) -> tuple:
    node = item.get("node", {})
    priority = _query_node_priority(node.get("type", ""), target_types)
    sources = set(item.get("retrieval_sources", []))
    hybrid_rank = 0 if {"exact", "semantic"} <= sources else 1 if "exact" in sources else 2 if "semantic" in sources else 3
    return (
        priority,
        hybrid_rank,
        -float(item.get("exact_score", 0.0)),
        -float(item.get("semantic_score", 0.0)),
        int(item.get("best_rank", 9999)),
        node.get("name", ""),
    )


def _group_query_match_key(item: Dict[str, Any], target_types: List[str]) -> tuple:
    node = item.get("node", {})
    priority = _query_node_priority(node.get("type", ""), target_types)
    sources = set(item.get("retrieval_sources", []))
    hybrid_rank = 0 if {"exact", "semantic"} <= sources else 1 if "exact" in sources else 2 if "semantic" in sources else 3
    return (
        priority,
        hybrid_rank,
        -float(item.get("rrf_score", 0.0)),
        -float(item.get("semantic_score", 0.0)),
        int(item.get("best_rank", 9999)),
        node.get("name", ""),
    )


def _query_node_priority(node_type: str, target_types: List[str]) -> int:
    priorities: Dict[str, int] = {}
    types = set(target_types)
    if {"FeignClient", "FeignMethod", "Endpoint"} & types:
        priorities.update({"FeignClient": 0, "FeignMethod": 1, "Endpoint": 2, "Class": 3, "Method": 4, "File": 5})
    if {"MQTopic", "MQConsumer"} & types:
        priorities.update({"MQTopic": 0, "MQConsumer": 1, "ConfigKey": 2, "Class": 3, "File": 4})
    if "ConfigKey" in types:
        priorities.update({"ConfigKey": 0, "Class": 1, "File": 2})
    if not priorities:
        priorities.update({"Class": 0, "Method": 1, "Field": 2, "File": 3})
    return priorities.get(node_type, 20)


def _merge_group_semantic_hit(
    merged: Dict[str, Dict[str, Any]],
    workspace_ref: str,
    workspace_name: str,
    hit: Dict[str, Any],
    workspace_matches: List[Dict[str, Any]],
    target_types: set[str],
) -> None:
    node = hit.get("node") or {}
    node_id = node.get("id")
    if not node_id:
        return
    if node.get("type"):
        target_types.add(node.get("type"))
    key = f"{workspace_ref}:{node_id}"
    current = merged.setdefault(
        key,
        {
            "workspace_ref": workspace_ref,
            "workspace": workspace_name,
            "node": node,
            "neighbors": _find_group_query_neighbors(workspace_matches, node_id),
            "rrf_score": 0.0,
            "semantic_score": 0.0,
            "best_rank": 9999,
            "retrieval_sources": [],
        },
    )
    current["semantic_score"] = max(current["semantic_score"], float(hit.get("score", 0.0)))
    if "semantic" not in current["retrieval_sources"]:
        current["retrieval_sources"].append("semantic")
    if not current.get("neighbors"):
        current["neighbors"] = _find_group_query_neighbors(workspace_matches, node_id)


def _find_group_query_neighbors(workspace_matches: List[Dict[str, Any]], node_id: str) -> List[Dict[str, Any]]:
    for item in workspace_matches:
        if item.get("node", {}).get("id") == node_id:
            return item.get("neighbors", [])
    return []


def _summarize_group_query_matches(matches: List[Dict[str, Any]], limit: int) -> Dict[str, int]:
    summary = {"exact_matches": 0, "semantic_matches": 0, "hybrid_matches": 0, "total_matches": len(matches), "returned_matches": min(len(matches), limit)}
    for item in matches:
        sources = set(item.get("retrieval_sources", []))
        if "exact" in sources:
            summary["exact_matches"] += 1
        if "semantic" in sources:
            summary["semantic_matches"] += 1
        if {"exact", "semantic"} <= sources:
            summary["hybrid_matches"] += 1
    return summary


def _summarize_query_matches(matches: List[Dict[str, Any]], limit: int) -> Dict[str, int]:
    return _summarize_group_query_matches(matches, limit)


def _build_lookup_payload(result: Dict[str, Any], match_key: str = "matches", limit: int = 5) -> Dict[str, Any]:
    matches = result.get(match_key, [])[:limit]
    return {
        "query": result.get("query", result.get("target", result.get("name", ""))),
        "retrieval_summary": result.get("retrieval_summary", {}),
        "entrypoints": [
            {
                "node": item.get("node", {}),
                "retrieval_sources": item.get("retrieval_sources", []),
                "exact_score": item.get("exact_score", item.get("rrf_score", 0.0)),
                "semantic_score": item.get("semantic_score", 0.0),
                "workspace_ref": item.get("workspace_ref", ""),
                "workspace": item.get("workspace", ""),
            }
            for item in matches
        ],
    }


def _build_context_evidence_summary(incoming: List[Dict[str, Any]], outgoing: List[Dict[str, Any]]) -> Dict[str, Any]:
    all_edges = incoming + outgoing
    return {
        "incoming_edges": len(incoming),
        "outgoing_edges": len(outgoing),
        "high_confidence_edges": sum(1 for item in all_edges if float(item.get("confidence", 0.0)) >= 0.80),
        "edge_types": sorted({item.get("type", "") for item in all_edges if item.get("type")}),
    }


def _build_impact_evidence_summary(confirmed: List[Dict[str, Any]], probable: List[Dict[str, Any]], possible: List[Dict[str, Any]]) -> Dict[str, Any]:
    impacts = confirmed + probable + possible
    return {
        "confirmed_count": len(confirmed),
        "probable_count": len(probable),
        "possible_count": len(possible),
        "edge_types": sorted({item.get("type", "") for item in impacts if item.get("type")}),
    }


def _build_group_impact_evidence_summary(
    confirmed: List[Dict[str, Any]],
    probable: List[Dict[str, Any]],
    possible: List[Dict[str, Any]],
    bridges: List[Dict[str, Any]],
) -> Dict[str, Any]:
    all_items = confirmed + probable + possible
    graph_items = [item for item in all_items if item.get("kind") == "graph"]
    bridge_items = [item for item in all_items if item.get("kind") == "bridge"]
    return {
        "confirmed_count": len(confirmed),
        "probable_count": len(probable),
        "possible_count": len(possible),
        "graph_evidence_count": len(graph_items),
        "bridge_evidence_count": len(bridge_items),
        "bridge_types": sorted({item.get("type", "") for item in bridges if item.get("type")}),
        "graph_edge_types": sorted({item.get("impact", {}).get("type", "") for item in graph_items if item.get("impact", {}).get("type")}),
    }


def _load_group_data(members: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    items = []
    for member in members:
        config, store = load_context(member["workspace_file"])
        items.append(
            {
                "name": member["name"],
                "workspace_ref": member["name"],
                "workspace": config.workspace,
                "workspace_file": member["workspace_file"],
                "services": [s.__dict__ for s in config.services],
                "feigns": store.read_json("feign-index.json", []),
                "apis": store.read_json("api-index.json", []),
                "mq": store.read_json("mq-index.json", []),
                "configs": store.read_json("config-index.json", []),
            }
        )
    return items


def _build_group_bridges(group_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    bridges: List[Dict[str, Any]] = []
    service_targets: Dict[str, List[Dict[str, Any]]] = {}
    apis: List[Dict[str, Any]] = []
    mq_topics: Dict[str, List[Dict[str, Any]]] = {}
    config_keys: Dict[str, List[Dict[str, Any]]] = {}
    config_values: Dict[str, List[Dict[str, Any]]] = {}

    for item in group_data:
        for svc in item["services"]:
            for key in {svc.get("name"), svc.get("service_name")}:
                if key:
                    service_targets.setdefault(str(key), []).append({"workspace_ref": item["workspace_ref"], "workspace": item["workspace"], "service": svc})
        for api in item["apis"]:
            apis.append({"workspace_ref": item["workspace_ref"], "workspace": item["workspace"], **api})
        for mq in item["mq"]:
            mq_topics.setdefault(mq.get("topic", ""), []).append({"workspace_ref": item["workspace_ref"], "workspace": item["workspace"], **mq})
        for cfg in item["configs"]:
            for key, value in cfg.get("values", {}).items():
                entry = {"workspace_ref": item["workspace_ref"], "workspace": item["workspace"], "project": cfg.get("project"), "path": cfg.get("path"), "key": key, "value": value}
                config_keys.setdefault(key, []).append(entry)
                config_values.setdefault(value, []).append(entry)

    for item in group_data:
        for feign in item["feigns"]:
            target_service = feign.get("target_service")
            for target in service_targets.get(target_service, []):
                bridges.append(
                    {
                        "type": "FEIGN_SERVICE",
                        "confidence": 0.95,
                        "source_workspace": item["workspace_ref"],
                        "source_workspace_name": item["workspace"],
                        "source_project": feign.get("project"),
                        "source_file": feign.get("file"),
                        "target_workspace": target["workspace_ref"],
                        "target_workspace_name": target["workspace"],
                        "target_project": target["service"].get("name"),
                        "target_file": "",
                        "summary": f"{feign.get('interface')} -> {target_service}",
                        "evidence": {"target_service": target_service, "feign": feign.get("interface")},
                    }
                )
            for method in feign.get("methods", []):
                for api in apis:
                    if method.get("http_method") == api.get("http_method") and method.get("path") == api.get("path"):
                        bridges.append(
                            {
                                "type": "FEIGN_ENDPOINT",
                                "confidence": 0.88,
                                "source_workspace": item["workspace_ref"],
                                "source_workspace_name": item["workspace"],
                                "source_project": feign.get("project"),
                                "source_file": feign.get("file"),
                                "target_workspace": api.get("workspace_ref"),
                                "target_workspace_name": api.get("workspace"),
                                "target_project": api.get("project"),
                                "target_file": api.get("file"),
                                "summary": f"{feign.get('interface')}.{method.get('method_name')} -> {api.get('http_method')} {api.get('path')}",
                                "evidence": {"path": api.get("path"), "http_method": api.get("http_method")},
                            }
                        )

    for topic, consumers in mq_topics.items():
        if not topic:
            continue
        for consumer in consumers:
            for cfg in config_values.get(topic, []):
                bridges.append(
                    {
                        "type": "MQ_TOPIC_CONFIG",
                        "confidence": 0.84,
                        "source_workspace": cfg.get("workspace_ref"),
                        "source_workspace_name": cfg.get("workspace"),
                        "source_project": cfg.get("project"),
                        "source_file": cfg.get("path"),
                        "target_workspace": consumer.get("workspace_ref"),
                        "target_workspace_name": consumer.get("workspace"),
                        "target_project": consumer.get("project"),
                        "target_file": consumer.get("file"),
                        "summary": f"{cfg.get('key')} = {topic} -> consumer {consumer.get('class_name')}",
                        "evidence": {"topic": topic, "config_key": cfg.get("key")},
                    }
                )
        if len(consumers) >= 2:
            primary = consumers[0]
            for other in consumers[1:]:
                bridges.append(
                    {
                        "type": "MQ_TOPIC_SHARED",
                        "confidence": 0.72,
                        "source_workspace": primary.get("workspace_ref"),
                        "source_workspace_name": primary.get("workspace"),
                        "source_project": primary.get("project"),
                        "source_file": primary.get("file"),
                        "target_workspace": other.get("workspace_ref"),
                        "target_workspace_name": other.get("workspace"),
                        "target_project": other.get("project"),
                        "target_file": other.get("file"),
                        "summary": f"shared topic {topic}",
                        "evidence": {"topic": topic},
                    }
                )

    for key, entries in config_keys.items():
        if len(entries) < 2:
            continue
        primary = entries[0]
        for other in entries[1:]:
            bridges.append(
                {
                    "type": "CONFIG_KEY_SHARED",
                    "confidence": 0.66,
                    "source_workspace": primary.get("workspace_ref"),
                    "source_workspace_name": primary.get("workspace"),
                    "source_project": primary.get("project"),
                    "source_file": primary.get("path"),
                    "target_workspace": other.get("workspace_ref"),
                    "target_workspace_name": other.get("workspace"),
                    "target_project": other.get("project"),
                    "target_file": other.get("path"),
                    "summary": f"shared config key {key}",
                    "evidence": {"config_key": key, "values": [primary.get('value'), other.get('value')]},
                }
            )

    deduped: Dict[str, Dict[str, Any]] = {}
    for bridge in bridges:
        key = "|".join(
            [
                bridge.get("type", ""),
                bridge.get("source_workspace", ""),
                bridge.get("source_project", ""),
                bridge.get("target_workspace", ""),
                bridge.get("target_project", ""),
                bridge.get("summary", ""),
            ]
        )
        deduped[key] = bridge
    return list(deduped.values())


def _count_bridges(bridges: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for bridge in bridges:
        bridge_type = bridge.get("type", "unknown")
        counts[bridge_type] = counts.get(bridge_type, 0) + 1
    return counts


def _filter_bridges(bridges: List[Dict[str, Any]], query: str, limit: int) -> List[Dict[str, Any]]:
    tokens = tokenize(query)
    if not tokens:
        return bridges[:limit]
    matched = []
    for bridge in bridges:
        haystack = json.dumps(bridge, ensure_ascii=False).lower()
        if any(token in haystack for token in tokens):
            matched.append(bridge)
    matched.sort(key=lambda item: (-float(item.get("confidence", 0)), item.get("summary", "")))
    return matched[:limit]


def _filter_impact_bridges(bridges: List[Dict[str, Any]], target: str, target_types: List[str], limit: int) -> List[Dict[str, Any]]:
    allowed_types = _bridge_types_for_target(target, target_types)
    filtered = [bridge for bridge in bridges if bridge.get("type") in allowed_types] if allowed_types else list(bridges)
    return _filter_bridges(filtered, target, limit)


def _bridge_types_for_target(target: str, target_types: List[str]) -> set[str]:
    allowed: set[str] = set()
    for target_type in target_types:
        if target_type in {"FeignClient", "FeignMethod", "Endpoint"}:
            allowed.update({"FEIGN_SERVICE", "FEIGN_ENDPOINT"})
        elif target_type in {"MQTopic", "MQConsumer"}:
            allowed.update({"MQ_TOPIC_CONFIG", "MQ_TOPIC_SHARED"})
        elif target_type == "ConfigKey":
            allowed.update({"CONFIG_KEY_SHARED", "MQ_TOPIC_CONFIG"})
    target_lower = target.lower()
    if not allowed:
        if "feign" in target_lower or "controller" in target_lower or target_lower.startswith("/"):
            allowed.update({"FEIGN_SERVICE", "FEIGN_ENDPOINT"})
        elif "topic" in target_lower or "kafka" in target_lower or "rocketmq" in target_lower:
            allowed.update({"MQ_TOPIC_CONFIG", "MQ_TOPIC_SHARED"})
        elif "." in target_lower:
            allowed.update({"CONFIG_KEY_SHARED", "MQ_TOPIC_CONFIG"})
    return allowed


def _resolve_group_target_types(target: str, target_types: List[str]) -> List[str]:
    resolved = set(t for t in target_types if t)
    target_lower = target.lower()
    topic_like = any(token in target_lower for token in ["topic", "kafka", "rocketmq"]) or "-" in target_lower
    if "feign" in target_lower:
        resolved.update({"FeignClient", "FeignMethod"})
    if target_lower.startswith("/") or any(token in target_lower for token in ["controller", "endpoint"]):
        resolved.add("Endpoint")
    if topic_like:
        resolved.add("MQTopic")
    if "." in target_lower and not topic_like:
        resolved.add("ConfigKey")
    if topic_like and "MQTopic" in resolved:
        resolved.discard("ConfigKey")
    return _sort_target_types(list(resolved))


def _sort_target_types(target_types: List[str]) -> List[str]:
    priority = {
        "FeignClient": 0,
        "FeignMethod": 1,
        "Endpoint": 2,
        "MQTopic": 3,
        "MQConsumer": 4,
        "ConfigKey": 5,
        "Field": 6,
        "Method": 7,
        "Class": 8,
        "File": 20,
    }
    return sorted({item for item in target_types if item}, key=lambda item: (priority.get(item, 10), item))


def _filter_group_impact_records(records: List[Dict[str, Any]], target_types: List[str]) -> List[Dict[str, Any]]:
    allowed_edges = _graph_edge_types_for_target(target_types)
    filtered = []
    for record in records:
        if record.get("kind") != "graph":
            filtered.append(record)
            continue
        edge_type = record.get("impact", {}).get("type")
        if not allowed_edges or edge_type in allowed_edges:
            filtered.append(record)
    return filtered


def _sort_group_impact_records(records: List[Dict[str, Any]], target_types: List[str]) -> List[Dict[str, Any]]:
    return sorted(records, key=lambda item: _group_impact_record_key(item, target_types))


def _group_impact_record_key(record: Dict[str, Any], target_types: List[str]) -> tuple:
    impact = record.get("impact", {})
    if record.get("kind") == "bridge":
        return _bridge_sort_key(impact, target_types)
    edge_type = impact.get("type", "")
    confidence = -float(impact.get("confidence", 0))
    depth = int(impact.get("depth", 99))
    priority = _graph_edge_priority(edge_type, target_types)
    return (priority, confidence, depth, edge_type)


def _graph_edge_types_for_target(target_types: List[str]) -> set[str]:
    allowed: set[str] = set()
    types = set(target_types)
    if {"FeignClient", "FeignMethod", "Endpoint"} & types:
        allowed.update({"INJECTS_BEAN", "IMPORTS", "CALLS_SERVICE", "IMPLEMENTS_FEIGN", "CALLS_METHOD", "HANDLES_ENDPOINT"})
    if {"MQTopic", "MQConsumer"} & types:
        allowed.update({"CONSUMES_TOPIC", "READS_CONFIG", "CALLS_METHOD", "INJECTS_BEAN"})
    if "ConfigKey" in types:
        allowed.update({"READS_CONFIG", "DECLARES_CONFIG"})
    if "Field" in types:
        allowed.update({"READS_FIELD", "CALLS_METHOD", "INJECTS_BEAN"})
    if not allowed and "Class" in types:
        allowed.update({"INJECTS_BEAN", "CALLS_METHOD", "IMPORTS"})
    return allowed


def _graph_edge_priority(edge_type: str, target_types: List[str]) -> int:
    priorities: Dict[str, int] = {}
    types = set(target_types)
    if {"FeignClient", "FeignMethod", "Endpoint"} & types:
        priorities.update(
            {
                "CALLS_SERVICE": 0,
                "IMPLEMENTS_FEIGN": 1,
                "HANDLES_ENDPOINT": 2,
                "INJECTS_BEAN": 3,
                "CALLS_METHOD": 4,
                "IMPORTS": 5,
            }
        )
    if {"MQTopic", "MQConsumer"} & types:
        priorities.update(
            {
                "CONSUMES_TOPIC": 0,
                "READS_CONFIG": 1,
                "CALLS_METHOD": 2,
                "INJECTS_BEAN": 3,
            }
        )
    if "ConfigKey" in types:
        priorities.update({"READS_CONFIG": 0, "DECLARES_CONFIG": 1})
    if "Field" in types:
        priorities.update({"READS_FIELD": 0, "CALLS_METHOD": 1, "INJECTS_BEAN": 2})
    if not priorities:
        priorities.update({"INJECTS_BEAN": 0, "CALLS_METHOD": 1, "IMPORTS": 2})
    return priorities.get(edge_type, 20)


def _sort_bridges(bridges: List[Dict[str, Any]], target_types: List[str]) -> List[Dict[str, Any]]:
    return sorted(bridges, key=lambda item: _bridge_sort_key(item, target_types))


def _bridge_sort_key(bridge: Dict[str, Any], target_types: List[str]) -> tuple:
    bridge_type = bridge.get("type", "")
    confidence = -float(bridge.get("confidence", 0))
    priority = _bridge_priority(bridge_type, target_types)
    return (priority, confidence, bridge_type, bridge.get("summary", ""))


def _bridge_priority(bridge_type: str, target_types: List[str]) -> int:
    priorities: Dict[str, int] = {}
    types = set(target_types)
    if {"FeignClient", "FeignMethod", "Endpoint"} & types:
        priorities.update({"FEIGN_ENDPOINT": 0, "FEIGN_SERVICE": 1})
    if {"MQTopic", "MQConsumer"} & types:
        priorities.update({"MQ_TOPIC_CONFIG": 0, "MQ_TOPIC_SHARED": 1})
    if "ConfigKey" in types:
        priorities.update({"MQ_TOPIC_CONFIG": 0, "CONFIG_KEY_SHARED": 1})
    return priorities.get(bridge_type, 20)

def _unknown_static_analysis_risks() -> List[str]:
    return [
        "反射、动态代理、AOP 切面、运行时生成调用链未做精确解析",
        "MyBatis XML / SQL 字段引用当前只做轻量级索引，未做完整 SQL 语义分析",
        "远程 Nacos 配置未默认拉取；只分析本地 application/bootstrap 配置",
        "泛型、重载、继承分派和条件 Bean 的类型解析仍可能存在保守估计",
    ]

def _impact_checklist(node: Dict[str, Any], risk_level: str) -> List[str]:
    base = ["确认上游调用方", "确认下游实现方", "确认是否需要联调或回放历史消息"]
    if node["type"] in {"FeignClient", "FeignMethod", "DTO"}:
        base += ["公共契约变更必须检查所有消费者", "字段删除/改义必须保留兼容周期"]
    if node["type"] in {"MQTopic", "MQConsumer"}:
        base += ["检查重复消费幂等", "检查失败重试/死信/补偿", "检查历史消息反序列化兼容"]
    if risk_level == "high":
        base += ["建议生成变更影响报告并在 PR 中附上"]
    return base
