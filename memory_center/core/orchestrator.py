from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

from .artifacts import (
    append_change_log,
    append_task_change_log,
    CORE_MEMORY_BLOCKS,
    create_task_space,
    get_artifact,
    get_task_artifact,
    list_task_spaces,
    resolve_task_space,
    touch_task_activity,
    update_artifact,
    update_task_artifact,
)
from .config import load_workspace_config
from .evals import EvalResultBuilder
from .registry import resolve_group
from .rules import (
    DEFAULT_AUTO_SYNC_RULES,
    DEFAULT_EVAL_RULES,
    DEFAULT_HANDOFF_PROFILES,
    DEFAULT_HANDOFF_RULES,
    DEFAULT_RESUME_RULES,
    DEFAULT_WRITE_POLICY_RULES,
    ensure_default_rules,
    load_yaml_rule_config,
    match_rules,
)
from .schemas import with_schema
from .semantic import semantic_index_stats, semantic_query
from .store import WorkspaceStore
from .text_utils import base_tokenize
from .timeline import timeline_query
from .write_receipts import WRITE_RECEIPTS_FILE, build_write_receipt, persist_write_receipt, query_write_receipts

SESSION_EVENTS_FILE = "session-events.jsonl"
SESSION_SUMMARIES_FILE = "session-summaries.jsonl"
EVENT_PAYLOAD_INLINE_LIMIT = 4000
LAYER_L0 = "L0_session_events"
LAYER_L1 = "L1_case_atoms"
LAYER_L2 = "L2_task_spaces"
LAYER_L3 = "L3_workspace_profile"
MEMORY_LAYER_ORDER = [LAYER_L0, LAYER_L1, LAYER_L2, LAYER_L3]
TOOL_WORKSPACE_LOG_SESSION_EVENT = "workspace_log_session_event"
TOOL_WORKSPACE_START_SESSION = "workspace_start_session"
TOOL_WORKSPACE_RECORD_CASE = "workspace_record_case"
TOOL_WORKSPACE_SUGGEST_CASE = "workspace_suggest_case"
TOOL_WORKSPACE_SYNC_SNIFF_ARTIFACTS = "workspace_sync_sniff_artifacts"
TOOL_WORKSPACE_SYNC_CASE_ARTIFACTS = "workspace_sync_case_artifacts"
TOOL_WORKSPACE_ARTIFACT_UPDATE = "workspace_artifact_update"


def load_context(workspace_file: str | Path):
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    return config, store


def workspace_status(workspace_file: str | Path, view: str = "full") -> Dict[str, Any]:
    config, store = load_context(workspace_file)
    active_tasks = _active_task_summaries(workspace_file, limit=5)
    current_focus_task = dict(active_tasks[0]) if active_tasks else None
    memory_layers = _build_memory_layers(store, active_tasks)
    core_memory_blocks = _build_core_memory_blocks_status(store)
    if current_focus_task:
        current_focus_task["focus_reason"] = _build_focus_reason(current_focus_task)
    result = {
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
        "memory_layers": memory_layers,
        "memory_overview": _build_memory_overview(memory_layers),
        "write_receipts_overview": _build_write_receipts_overview(store),
        "continuity_overview": _build_continuity_overview(workspace_file, active_tasks),
        "core_memory_blocks": core_memory_blocks,
        "active_task_spaces": active_tasks,
        "current_focus_task": current_focus_task,
        "topology": store.read_json("service-topology.json", {}),
    }
    return _compact_workspace_status(result) if _is_compact_view(view) else result


def workspace_sniff(
    workspace_file: str | Path,
    intent: str,
    limit: int = 12,
    auto_sync_mode: str = "balanced",
    include_lookup_hint: bool = True,
    view: str = "full",
) -> Dict[str, Any]:
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
    recent_sessions = store.read_jsonl(SESSION_SUMMARIES_FILE, limit=30)
    rules = match_rules(store, intent=intent, files=[x["path"] for x in matched_files])[:10]
    sniff_risk_level = _sniff_risk_level(intent, matched_files, related_feigns, related_apis, related_mq, rules)
    task_resolution = resolve_task_space(
        workspace_file,
        intent=intent,
        create_if_missing=False,
        limit_candidates=3,
        related_texts=[item.get("task", "") for item in related_cases] + [item.get("summary", "") or item.get("intent", "") for item in recent_sessions],
    )
    auto_sync = _build_sniff_auto_sync_recommendation(store, task_resolution, sniff_risk_level, auto_sync_mode=auto_sync_mode)
    source_refs = _build_sniff_source_refs(matched_files, related_feigns, related_apis, related_mq, related_cases)
    write_judge_recommendation = memory_write_judge(
        workspace_file,
        text=intent,
        source="sniff_intent",
        intent=intent,
        projects=matched_services[:5],
        files=[item.get("path", "") for item in matched_files[:8]],
    )
    lookup_hint_context = {
        "risk_level": sniff_risk_level,
        "matched_services": matched_services,
        "candidate_files": matched_files,
    }
    lookup_hint = (
        workspace_lookup_hint(
            workspace_file,
            query=intent,
            intent=intent,
            limit=min(limit, 6),
            sniff_context=lookup_hint_context,
        )
        if include_lookup_hint
        else None
    )

    result = {
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
        "source_refs": source_refs,
        "resolved_task": {
            key: task_resolution.get(key)
            for key in [
                "resolved",
                "task_id",
                "title",
                "status",
                "owner",
                "tags",
                "priority",
                "score",
                "match_reasons",
                "score_threshold",
            ]
        },
        "auto_sync_recommendation": auto_sync,
        "write_judge_recommendation": write_judge_recommendation.get("decision", {}),
        "lookup_hint": {
            "recommended_path": lookup_hint.get("recommended_path", "") if lookup_hint else "",
            "preferred_tools": lookup_hint.get("preferred_tools", []) if lookup_hint else [],
            "should_use_memory_center": lookup_hint.get("should_use_memory_center", False) if lookup_hint else False,
            "reasons": lookup_hint.get("reasons", []) if lookup_hint else [],
        },
        "symbolic_context": _build_sniff_symbolic_context(intent, sniff_risk_level, matched_services, matched_files, related_feigns, related_apis, related_mq, related_cases),
        "next_steps": [
            "先调用 memory_search_code 缩小入口范围，再用 memory_symbol 定位关键符号",
            "对关键符号调用 memory_callers / memory_callees 理清上下游调用链",
            "先调用 memory_write_judge / memory_plan_write 判断信息应写入 L0/L1/L2/L3，再执行对应写入工具",
            "如果这是持续任务或多人协作任务，优先调用 workspace_sync_sniff_artifacts 把 context/plan 写入任务空间",
            "改动前调用 memory_plan_change 与 memory_verify_checklist，明确风险与验证项",
            "如果涉及 DTO/Feign/MQ Message，再调用 workspace_check_contract",
            "长任务建议同时开启 workspace_start_session / workspace_log_session_event，结束后再调用 workspace_sync_case_artifacts 与 workspace_record_case",
        ],
    }
    return _compact_sniff_result(result) if _is_compact_view(view) else result


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


def workspace_lookup_hint(
    workspace_file: str | Path,
    query: str,
    intent: str = "",
    limit: int = 8,
    sniff_context: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    config, _ = load_context(workspace_file)
    normalized = f"{query} {intent}".strip().lower()
    reasons: List[str] = []
    preferred_tools: List[str] = []
    recommended_path = "local_search"
    should_use_memory_center = False

    if any(token in normalized for token in ["controller", "service", "client", "feign", "dto", "entity", "mapper", "consumer", "producer", "topic", "config", "class", "method", "类", "方法", "配置"]):
        preferred_tools = ["memory_symbol_tool", "memory_search_code_tool"]
        recommended_path = "symbol_lookup"
        should_use_memory_center = True
        reasons.append("查询看起来在找类、方法、Feign、Topic 或配置项，优先走符号/索引检索更稳。")

    if any(token in normalized for token in ["谁调用", "调用链", "caller", "callee", "upstream", "downstream", "依赖", "链路"]):
        preferred_tools = ["memory_callers_tool", "memory_callees_tool", "workspace_trace_tool"]
        recommended_path = "call_chain"
        should_use_memory_center = True
        reasons.append("查询包含调用链或依赖分析语义，适合先走图谱链路工具。")

    if any(token in normalized for token in ["跨服务", "影响", "风险", "契约", "mq", "kafka", "rocketmq", "api", "接口"]):
        preferred_tools = ["workspace_sniff_tool", "memory_impact_tool", "memory_context_tool"]
        recommended_path = "cross_service_analysis"
        should_use_memory_center = True
        reasons.append("查询涉及跨服务、契约或风险分析，Memory Center 的上下文价值更高。")

    if not preferred_tools and any(token in normalized for token in ["文件", "路径", "字符串", "关键字", "grep", "文本"]):
        preferred_tools = ["memory_search_code_tool"]
        recommended_path = "keyword_lookup"
        should_use_memory_center = True
        reasons.append("查询偏关键词入口定位，先走代码索引检索通常比全仓库扫描更省上下文。")

    if not preferred_tools:
        preferred_tools = ["local_search", "memory_search_code_tool"]
        reasons.append("查询更像局部实现细节确认，可先本地搜索；若范围扩大，再切到 Memory Center。")

    if sniff_context is None:
        sniff = workspace_sniff(workspace_file, query or intent, limit=min(limit, 6), include_lookup_hint=False)
    else:
        sniff = sniff_context
    return with_schema(
        "lookup_hint",
        {
            "workspace": config.workspace,
            "query": query,
            "intent": intent,
            "recommended_path": recommended_path,
            "preferred_tools": preferred_tools,
            "reasons": reasons,
            "should_use_memory_center": should_use_memory_center,
            "sniff_risk_level": sniff.get("risk_level", ""),
            "matched_services": sniff.get("matched_services", [])[:5],
            "candidate_files": sniff.get("candidate_files", [])[:5],
            "fallback": "若推荐结果不足以定位，再退回本地 grep / rg 做小范围确认。",
        },
    )


def memory_tool_usage_report(
    workspace_file: str | Path,
    limit: int = 200,
) -> Dict[str, Any]:
    config, store = load_context(workspace_file)
    events = store.read_jsonl(SESSION_EVENTS_FILE, limit=max(limit, 1))
    tool_counts: Dict[str, int] = {}
    lookup_tool_counts: Dict[str, int] = {}
    memory_center_calls = 0
    external_calls = 0
    suspected_bypass: List[Dict[str, Any]] = []
    lookup_tools = {
        "memory_symbol_tool",
        "memory_search_code_tool",
        "workspace_trace_tool",
        "memory_callers_tool",
        "memory_callees_tool",
        "memory_context_tool",
        "memory_impact_tool",
        "workspace_sniff_tool",
    }

    for event in events:
        if event.get("event_type") != "tool_call":
            continue
        payload = _event_payload(event)
        tool_name = str(payload.get("tool_name") or payload.get("name") or "")
        if not tool_name:
            continue
        tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1
        is_memory_center = tool_name.startswith("memory_") or tool_name.startswith("workspace_")
        if is_memory_center:
            memory_center_calls += 1
        else:
            external_calls += 1
        if tool_name in lookup_tools:
            lookup_tool_counts[tool_name] = lookup_tool_counts.get(tool_name, 0) + 1
        payload_text = json.dumps(payload, ensure_ascii=False).lower()
        if not is_memory_center and any(token in payload_text for token in ["class", "method", "feign", "topic", "caller", "callee", "symbol", "controller", "service", "类", "方法", "调用链"]):
            suspected_bypass.append(
                {
                    "session_id": event.get("session_id", ""),
                    "tool_name": tool_name,
                    "query": payload.get("query", "") or payload.get("target", "") or payload.get("text", ""),
                    "reason": "看起来是在做类/符号/调用链检索，但没有走 Memory Center 工具。",
                }
            )

    total_tool_calls = memory_center_calls + external_calls
    summary = {
        "total_tool_calls": total_tool_calls,
        "memory_center_calls": memory_center_calls,
        "external_calls": external_calls,
        "memory_center_ratio": round((memory_center_calls / total_tool_calls), 3) if total_tool_calls else 0.0,
        "lookup_tool_total": sum(lookup_tool_counts.values()),
        "suspected_bypass_count": len(suspected_bypass),
    }
    adoption_hints: List[str] = []
    if sum(lookup_tool_counts.values()) == 0:
        adoption_hints.append("最近会话里几乎没有使用 Memory Center 的 lookup 工具，找类/符号很可能仍主要依赖本地搜索。")
    if suspected_bypass:
        adoption_hints.append("检测到疑似绕过案例，建议继续把类/符号/调用链检索优先协议前置到生成指令里。")
    if summary["memory_center_ratio"] < 0.4 and total_tool_calls:
        adoption_hints.append("Memory Center 工具调用占比较低，可能意味着协议优先级还不够高，或返回结果还不够有吸引力。")
    if not adoption_hints:
        adoption_hints.append("近期使用情况正常，Memory Center 已经开始承担主要检索与连续性职责。")

    return with_schema(
        "tool_usage_report",
        {
            "workspace": config.workspace,
            "summary": summary,
            "tool_counts": dict(sorted(tool_counts.items(), key=lambda item: (-item[1], item[0]))[:20]),
            "lookup_tool_counts": dict(sorted(lookup_tool_counts.items(), key=lambda item: (-item[1], item[0]))),
            "suspected_bypass": suspected_bypass[:20],
            "adoption_hints": adoption_hints,
        },
    )


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


def workspace_record_case(
    workspace_file: str | Path,
    task: str,
    projects: List[str],
    files: List[str],
    flow: str = "",
    risk_points: List[str] | None = None,
    verified_by: List[str] | None = None,
    source_session_id: str = "",
    source_task_id: str = "",
    source_refs: List[Dict[str, Any]] | None = None,
    valid_from: str = "",
    valid_to: str = "",
    superseded_by: str = "",
    current_truth: bool = True,
) -> Dict[str, Any]:
    _, store = load_context(workspace_file)
    item = {
        "task": task,
        "projects": projects,
        "files": files,
        "flow": flow,
        "risk_points": risk_points or [],
        "verified_by": verified_by or [],
        "memory_layer": "L1_case_atom",
        "source_session_id": source_session_id.strip(),
        "source_task_id": source_task_id.strip(),
        "source_refs": source_refs or [],
        "valid_from": valid_from.strip() or datetime.now(timezone.utc).isoformat(),
        "valid_to": valid_to.strip(),
        "superseded_by": superseded_by.strip(),
        "current_truth": bool(current_truth) and not superseded_by.strip() and not valid_to.strip(),
    }
    store.append_jsonl("cross-service-task-memory.jsonl", item)
    receipt = persist_write_receipt(
        store,
        build_write_receipt(
            layer=LAYER_L1,
            action=TOOL_WORKSPACE_RECORD_CASE,
            scope="memory",
            target="cross-service-task-memory.jsonl",
            target_file="memory/cross-service-task-memory.jsonl",
            source_session_id=item.get("source_session_id", ""),
            task_id=item.get("source_task_id", ""),
        ),
    )
    return {
        "recorded": True,
        "case": item,
        "write_receipt": receipt,
    }


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
    summaries = store.read_jsonl(SESSION_SUMMARIES_FILE, limit=max(limit, 1))
    return {
        "workspace": config.workspace,
        "recent_sessions": list(reversed(summaries[-limit:])),
    }


def workspace_session_summary(workspace_file: str | Path, session_id: str) -> Dict[str, Any]:
    config, store = load_context(workspace_file)
    summaries = store.find_jsonl(SESSION_SUMMARIES_FILE, lambda row: row.get("session_id") == session_id, limit=1)
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


def workspace_recent_evidence(
    workspace_file: str | Path,
    task_id: str = "",
    session_id: str = "",
    limit: int = 10,
) -> Dict[str, Any]:
    config, _ = load_context(workspace_file)
    result = timeline_query(str(workspace_file), task_id=task_id.strip(), session_id=session_id.strip(), kinds=["session_event", "write_receipt"], limit=limit)
    evidence: List[Dict[str, Any]] = []
    for item in result.get("timeline", []):
        if item.get("kind") == "session_event":
            raw = item.get("raw", {})
            payload = raw.get("payload", {}) if isinstance(raw.get("payload"), dict) else {}
            evidence.append(
                {
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
            )
        elif item.get("kind") == "write_receipt":
            evidence.append(
                {
                    "source": "write_receipt",
                    "layer": item.get("layer", ""),
                    "action": item.get("action", ""),
                    "task_id": item.get("task_id", ""),
                    "session_id": item.get("session_id", ""),
                    "target": item.get("target", ""),
                    "receipt_ref": item.get("receipt_ref", ""),
                    "created_at": item.get("created_at", ""),
                }
            )
    return {
        "workspace": config.workspace,
        "task_id": task_id,
        "session_id": session_id,
        "evidence": evidence[-limit:],
    }


def workspace_unresolved_items(
    workspace_file: str | Path,
    task_id: str = "",
    session_id: str = "",
    intent: str = "",
    limit: int = 10,
) -> Dict[str, Any]:
    config, _ = load_context(workspace_file)
    unresolved: List[str] = []
    quality = memory_eval_write_quality(workspace_file, task_id=task_id, session_id=session_id, intent=intent, limit=max(limit, 20))
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
) -> Dict[str, Any]:
    config, _ = load_context(workspace_file)
    actions: List[str] = []
    quality = memory_eval_write_quality(workspace_file, task_id=task_id, session_id=session_id, intent=intent, limit=max(limit, 20))
    layer_set = set(quality.get("layers_present", []))
    if session_id.strip() and LAYER_L0 not in layer_set:
        actions.append("先补 `workspace_log_session_event`，把关键过程写入 L0 session memory。")
    if task_id.strip() and LAYER_L2 not in layer_set:
        actions.append("先补 `workspace_sync_sniff_artifacts` 或 `workspace_sync_case_artifacts`，把任务上下文写入 L2 task space。")
    if session_id.strip() and LAYER_L1 not in layer_set:
        actions.append("补 `workspace_record_case`，把当前会话沉淀为 L1 case memory。")
    if any(k in intent.lower() for k in ["规则", "规范", "migration", "invariant"]) and LAYER_L3 not in layer_set:
        actions.append("补 `memory_execute_write` 或 `workspace_artifact_update`，把规则类信息写入 L3 核心记忆块。")
    unresolved = workspace_unresolved_items(workspace_file, task_id=task_id, session_id=session_id, intent=intent, limit=limit).get("items", [])
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


def workspace_resume_packet(
    workspace_file: str | Path,
    task_id: str = "",
    session_id: str = "",
    intent: str = "",
    limit: int = 10,
    view: str = "full",
) -> Dict[str, Any]:
    config, store = load_context(workspace_file)
    resolved_task_id = task_id.strip()
    focus_task = workspace_status(workspace_file).get("current_focus_task")
    if not resolved_task_id and focus_task:
        resolved_task_id = str(focus_task.get("task_id", "") or "")
    task_meta = None
    current_summary = ""
    if resolved_task_id:
        tasks = list_task_spaces(workspace_file, include_archived=True)
        task_meta = next((item for item in tasks.get("active_tasks", []) + tasks.get("archived_tasks", []) if item.get("task_id") == resolved_task_id), None)
        current_summary = get_task_artifact(workspace_file, resolved_task_id, "current_summary").get("content", "")
    resume_rules = _load_resume_rules(store, intent or current_summary)
    evidence = workspace_recent_evidence(workspace_file, task_id=resolved_task_id, session_id=session_id, limit=int(resume_rules.get("evidence_limit", limit))).get("evidence", [])
    next_actions = workspace_next_actions(workspace_file, task_id=resolved_task_id, session_id=session_id, intent=intent or current_summary, limit=int(resume_rules.get("action_limit", limit))).get("actions", [])
    unresolved = workspace_unresolved_items(workspace_file, task_id=resolved_task_id, session_id=session_id, intent=intent or current_summary, limit=int(resume_rules.get("unresolved_limit", limit))).get("items", [])
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
    return _compact_resume_packet(result) if _is_compact_view(view) else result


def workspace_model_profile(model_name: str, workspace_file: str | Path | None = None) -> Dict[str, Any]:
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


def workspace_handoff_packet(
    workspace_file: str | Path,
    target_model: str,
    task_id: str = "",
    session_id: str = "",
    intent: str = "",
    limit: int = 10,
) -> Dict[str, Any]:
    config, store = load_context(workspace_file)
    profile = workspace_model_profile(target_model, workspace_file=workspace_file)
    handoff_rules = _load_handoff_rules(store, profile.get("normalized_model", ""))
    resume_packet = workspace_resume_packet(workspace_file, task_id=task_id, session_id=session_id, intent=intent, limit=limit)
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
    packet = {
        "workspace": config.workspace,
        "target_model": target_model,
        "task_id": resume_packet.get("task_id", ""),
        "session_id": session_id,
        "model_profile": profile,
        "handoff_rule_profile": handoff_rules.get("profile_name", "default"),
        "handoff_packet": {k: v for k, v in packet_body.items() if k in handoff_rules.get("include_sections", list(packet_body.keys()))},
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
    return with_schema("handoff_packet", packet)


def workspace_continuity_dashboard(
    workspace_file: str | Path,
    intent: str = "",
    task_id: str = "",
    session_id: str = "",
    limit: int = 10,
    view: str = "full",
) -> Dict[str, Any]:
    status = workspace_status(workspace_file)
    focus_task_id = task_id or (status.get("current_focus_task") or {}).get("task_id", "")
    resume_packet = workspace_resume_packet(workspace_file, task_id=focus_task_id, session_id=session_id, intent=intent, limit=limit)
    next_actions = workspace_next_actions(workspace_file, task_id=focus_task_id, session_id=session_id, intent=intent, limit=limit)
    unresolved = workspace_unresolved_items(workspace_file, task_id=focus_task_id, session_id=session_id, intent=intent, limit=limit)
    receipts = workspace_write_receipts(workspace_file, task_id=focus_task_id, session_id=session_id, limit=limit)
    handoffs = workspace_handoff_history(workspace_file, task_id=focus_task_id, session_id=session_id, limit=limit)
    evidence = workspace_recent_evidence(workspace_file, task_id=focus_task_id, session_id=session_id, limit=limit)
    result = with_schema(
        "workspace_continuity_dashboard",
        {
        "workspace": status.get("workspace", ""),
        "focus_task": status.get("current_focus_task"),
        "continuity_overview": status.get("continuity_overview", {}),
        "resume_packet": resume_packet,
        "next_actions": next_actions.get("actions", []),
        "unresolved_items": unresolved.get("items", []),
        "recent_receipts": receipts.get("receipts", [])[-5:],
        "recent_handoffs": handoffs.get("handoffs", [])[-5:],
        "recent_evidence": evidence.get("evidence", [])[-5:],
        },
    )
    return _compact_continuity_dashboard(result) if _is_compact_view(view) else result


def workspace_dashboard(
    workspace_file: str | Path,
    intent: str = "",
    limit: int = 10,
    view: str = "full",
) -> Dict[str, Any]:
    status = workspace_status(workspace_file)
    active_tasks = status.get("active_task_spaces", [])[: max(limit, 1)]
    low_quality_tasks: List[Dict[str, Any]] = []
    resumable_tasks: List[Dict[str, Any]] = []
    blocked_tasks: List[Dict[str, Any]] = []

    for task in active_tasks:
        task_id = str(task.get("task_id", "") or "")
        title = str(task.get("title", "") or "")
        summary_preview = str(task.get("summary_preview", "") or "")
        quality = memory_eval_write_quality(workspace_file, task_id=task_id, intent=title or summary_preview, limit=10)
        entry = {
            "task_id": task_id,
            "title": title,
            "status": task.get("status", ""),
            "priority": task.get("priority", ""),
            "quality": quality.get("quality", ""),
            "score": quality.get("score", 0),
            "receipt_count": quality.get("receipt_count", 0),
            "summary_preview": summary_preview,
        }
        if task.get("status") == "blocked":
            blocked_tasks.append(entry)
        if summary_preview:
            resumable_tasks.append(entry)
        if quality.get("quality") != "high":
            low_quality_tasks.append(entry)

    timeline = timeline_query(str(workspace_file), kinds=["write_receipt", "handoff"], limit=limit * 3).get("timeline", [])
    receipts = [item for item in timeline if item.get("kind") == "write_receipt"][-limit:]
    handoffs = [item.get("raw", item) for item in timeline if item.get("kind") == "handoff"][-limit:]
    focus_task = status.get("current_focus_task")
    focus_dashboard = (
        workspace_continuity_dashboard(workspace_file, intent=intent, task_id=(focus_task or {}).get("task_id", ""), limit=min(limit, 5))
        if focus_task
        else None
    )
    focus_resume_eval = memory_eval_resume(
        workspace_file,
        task_id=(focus_task or {}).get("task_id", ""),
        intent=intent,
        limit=min(limit, 10),
    )
    usage_report = memory_tool_usage_report(workspace_file, limit=max(limit * 10, 50))
    result = with_schema(
        "workspace_dashboard",
        {
        "workspace": status.get("workspace", ""),
        "focus_task": focus_task,
        "continuity_overview": status.get("continuity_overview", {}),
        "write_receipts_overview": status.get("write_receipts_overview", {}),
        "active_tasks": active_tasks,
        "resumable_tasks": resumable_tasks[:limit],
        "blocked_tasks": blocked_tasks[:limit],
        "low_quality_tasks": sorted(low_quality_tasks, key=lambda item: (item.get("score", 0), item.get("task_id", "")))[:limit],
        "recent_receipts": receipts,
        "recent_handoffs": handoffs,
        "focus_dashboard": focus_dashboard,
        "focus_resume_eval": focus_resume_eval,
        "tool_usage_report": {
            "summary": usage_report.get("summary", {}),
            "lookup_tool_counts": usage_report.get("lookup_tool_counts", {}),
            "suspected_bypass": usage_report.get("suspected_bypass", [])[:5],
            "adoption_hints": usage_report.get("adoption_hints", []),
        },
        },
    )
    return _compact_workspace_dashboard(result) if _is_compact_view(view) else result


def workspace_handoff_history(
    workspace_file: str | Path,
    target_model: str = "",
    task_id: str = "",
    session_id: str = "",
    limit: int = 50,
) -> Dict[str, Any]:
    config, _ = load_context(workspace_file)
    normalized_target = _normalize_model_name(target_model) if target_model else ""
    timeline = timeline_query(str(workspace_file), task_id=task_id, session_id=session_id, kinds=["handoff"], limit=5000).get("timeline", [])
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
            "models": sorted({row.get("normalized_model", "") for row in matched if row.get("normalized_model")}),
        },
    }


def memory_write_judge(
    workspace_file: str | Path,
    text: str,
    source: str = "note",
    intent: str = "",
    prefer_layer: str = "",
    projects: List[str] | None = None,
    files: List[str] | None = None,
) -> Dict[str, Any]:
    config, store = load_context(workspace_file)
    normalized_text = (text or "").strip().lower()
    normalized_intent = (intent or "").strip().lower()
    normalized_source = (source or "").strip().lower()
    preferred = (prefer_layer or "").strip().upper()

    layer_scores: Dict[str, int] = {layer: 0 for layer in MEMORY_LAYER_ORDER}
    reasons: List[str] = []
    policy = _load_write_policy_rules(store)

    for layer, boost in (policy.get("source_layer_boosts", {}).get(normalized_source, {}) or {}).items():
        if layer in layer_scores:
            layer_scores[layer] += int(boost or 0)
    if normalized_source in (policy.get("source_layer_boosts", {}) or {}):
        reasons.append("来源命中了 write-policy-rules 的 source_layer_boosts。")

    for rule in policy.get("keyword_layer_boosts", []) or []:
        keywords = [str(item).lower() for item in rule.get("keywords", [])]
        if keywords and any(token in normalized_text for token in keywords):
            layer = str(rule.get("layer", "") or "")
            if layer in layer_scores:
                layer_scores[layer] += int(rule.get("score", 0) or 0)
                reasons.append(str(rule.get("reason", f"文本命中 {layer} 规则。")))

    for rule in policy.get("intent_layer_boosts", []) or []:
        keywords = [str(item).lower() for item in rule.get("keywords", [])]
        if normalized_intent and keywords and any(token in normalized_intent for token in keywords):
            layer = str(rule.get("layer", "") or "")
            if layer in layer_scores:
                layer_scores[layer] += int(rule.get("score", 0) or 0)
                reasons.append(str(rule.get("reason", f"意图命中 {layer} 规则。")))

    if projects:
        for layer, boost in (policy.get("projects_present_boosts", {}) or {}).items():
            if layer in layer_scores:
                layer_scores[layer] += int(boost or 0)
    if files:
        for layer, boost in (policy.get("files_present_boosts", {}) or {}).items():
            if layer in layer_scores:
                layer_scores[layer] += int(boost or 0)

    prefer_boost = int(policy.get("prefer_layer_boost", 3) or 3)
    if preferred in {"L0", "L0_SESSION_EVENTS"}:
        layer_scores[LAYER_L0] += prefer_boost
        reasons.append("用户偏好层级指向 L0。")
    if preferred in {"L1", "L1_CASE_ATOMS"}:
        layer_scores[LAYER_L1] += prefer_boost
        reasons.append("用户偏好层级指向 L1。")
    if preferred in {"L2", "L2_TASK_SPACES"}:
        layer_scores[LAYER_L2] += prefer_boost
        reasons.append("用户偏好层级指向 L2。")
    if preferred in {"L3", "L3_WORKSPACE_PROFILE"}:
        layer_scores[LAYER_L3] += prefer_boost
        reasons.append("用户偏好层级指向 L3。")

    ranked = sorted(layer_scores.items(), key=lambda item: item[1], reverse=True)
    selected_layer = ranked[0][0]
    top_score = ranked[0][1]
    second_score = ranked[1][1]
    confidence = "high" if top_score - second_score >= 3 else ("medium" if top_score - second_score >= 1 else "low")

    suggested_tool = TOOL_WORKSPACE_LOG_SESSION_EVENT
    suggested_action = "记录为会话事件（L0）"
    if selected_layer == LAYER_L1:
        suggested_tool = TOOL_WORKSPACE_RECORD_CASE
        suggested_action = "沉淀为可复用案例（L1）"
    elif selected_layer == LAYER_L2:
        suggested_tool = f"{TOOL_WORKSPACE_SYNC_SNIFF_ARTIFACTS} / {TOOL_WORKSPACE_SYNC_CASE_ARTIFACTS}"
        suggested_action = "同步到任务空间文档（L2）"
    elif selected_layer == LAYER_L3:
        suggested_tool = TOOL_WORKSPACE_ARTIFACT_UPDATE
        suggested_action = "写入工作区核心记忆块（L3）"

    return {
        "workspace": config.workspace,
        "input": {
            "source": source,
            "intent": intent,
            "prefer_layer": prefer_layer,
            "projects": projects or [],
            "files": files or [],
            "text_preview": text[:240],
        },
        "decision": {
            "selected_layer": selected_layer,
            "confidence": confidence,
            "layer_scores": layer_scores,
            "reasons": reasons[:8],
            "suggested_tool": suggested_tool,
            "suggested_action": suggested_action,
        },
    }


def memory_plan_write(
    workspace_file: str | Path,
    text: str,
    source: str = "note",
    intent: str = "",
    session_id: str = "",
    task_id: str = "",
    title: str = "",
    prefer_layer: str = "",
    projects: List[str] | None = None,
    files: List[str] | None = None,
) -> Dict[str, Any]:
    config, _ = load_context(workspace_file)
    judge = memory_write_judge(
        workspace_file,
        text=text,
        source=source,
        intent=intent,
        prefer_layer=prefer_layer,
        projects=projects,
        files=files,
    )
    selected_layer = judge["decision"]["selected_layer"]
    steps: List[Dict[str, Any]] = []

    if selected_layer == LAYER_L0:
        if session_id.strip():
            steps.append(
                {
                    "tool": TOOL_WORKSPACE_LOG_SESSION_EVENT,
                    "ready": True,
                    "purpose": "将信息作为会话事件写入 L0。",
                    "example_args": {
                        "session_id": session_id.strip(),
                        "event_type": source or "note",
                        "payload": {"text": text[:2000], "intent": intent},
                    },
                }
            )
        else:
            steps.append(
                {
                    "tool": TOOL_WORKSPACE_START_SESSION,
                    "ready": True,
                    "purpose": "缺少 session_id，先创建会话。",
                    "example_args": {"intent": intent or "写入记忆事件"},
                }
            )
            steps.append(
                {
                    "tool": TOOL_WORKSPACE_LOG_SESSION_EVENT,
                    "ready": False,
                    "purpose": "会话创建后写入事件。",
                    "required": ["session_id"],
                    "example_args": {"event_type": source or "note", "payload": {"text": text[:2000]}},
                }
            )
    elif selected_layer == LAYER_L1:
        ready = bool(projects and files)
        steps.append(
            {
                "tool": TOOL_WORKSPACE_RECORD_CASE,
                "ready": ready,
                "purpose": "将信息沉淀为 L1 案例。",
                "required": ([] if ready else ["projects", "files"]) + ([] if text.strip() else ["text/task"]),
                "example_args": {
                    "task": intent or "待补充任务标题",
                    "projects": projects or [],
                    "files": files or [],
                    "flow": "memory_write_judge -> record_case",
                    "risk_points": [text[:120]] if text.strip() else [],
                },
            }
        )
        if session_id.strip():
            steps.append(
                {
                    "tool": TOOL_WORKSPACE_SUGGEST_CASE,
                    "ready": True,
                    "purpose": "也可先用会话自动草拟 case 再确认入库。",
                    "example_args": {"session_id": session_id.strip()},
                }
            )
    elif selected_layer == LAYER_L2:
        if session_id.strip():
            steps.append(
                {
                    "tool": TOOL_WORKSPACE_SYNC_CASE_ARTIFACTS,
                    "ready": True,
                    "purpose": "从会话内容同步到 L2 任务空间（design/change-log/current-summary）。",
                    "example_args": {"session_id": session_id.strip(), "task_id": task_id.strip(), "title": title.strip()},
                }
            )
        else:
            steps.append(
                {
                    "tool": TOOL_WORKSPACE_SYNC_SNIFF_ARTIFACTS,
                    "ready": bool(intent.strip()),
                    "purpose": "从 intent 推导并同步到 L2 任务空间（context/plan/current-summary）。",
                    "required": [] if intent.strip() else ["intent"],
                    "example_args": {"intent": intent or text[:80], "task_id": task_id.strip(), "title": title.strip()},
                }
            )
    else:
        artifact_name = _choose_l3_artifact_name(text)
        steps.append(
            {
                "tool": TOOL_WORKSPACE_ARTIFACT_UPDATE,
                "ready": True,
                "purpose": "写入 L3 核心记忆块。",
                "example_args": {
                    "name": artifact_name,
                    "content": f"## Update\n\n{text[:2000]}",
                },
            }
        )

    return {
        "workspace": config.workspace,
        "memory_layer": selected_layer,
        "confidence": judge["decision"]["confidence"],
        "judge": judge["decision"],
        "plan": {
            "ready": all(bool(step.get("ready", False)) for step in steps),
            "steps": steps,
        },
    }


def memory_execute_write(
    workspace_file: str | Path,
    text: str,
    source: str = "note",
    intent: str = "",
    session_id: str = "",
    task_id: str = "",
    title: str = "",
    prefer_layer: str = "",
    projects: List[str] | None = None,
    files: List[str] | None = None,
) -> Dict[str, Any]:
    plan_result = memory_plan_write(
        workspace_file,
        text=text,
        source=source,
        intent=intent,
        session_id=session_id,
        task_id=task_id,
        title=title,
        prefer_layer=prefer_layer,
        projects=projects,
        files=files,
    )
    executed: List[Dict[str, Any]] = []
    current_session_id = session_id.strip()
    for step in plan_result.get("plan", {}).get("steps", []):
        tool = str(step.get("tool", "") or "")
        if tool == TOOL_WORKSPACE_START_SESSION:
            result = workspace_start_session(workspace_file, step.get("example_args", {}).get("intent", intent or "写入记忆事件"))
            current_session_id = str(result.get("session_id", "") or current_session_id)
            executed.append({"tool": tool, "result": result})
            continue
        if not step.get("ready", False):
            if tool == TOOL_WORKSPACE_LOG_SESSION_EVENT and current_session_id:
                result = workspace_log_session_event(
                    workspace_file,
                    current_session_id,
                    step.get("example_args", {}).get("event_type", source or "note"),
                    step.get("example_args", {}).get("payload", {"text": text[:2000], "intent": intent}),
                )
                executed.append({"tool": tool, "result": result, "auto_resolved": True})
                continue
            executed.append({"tool": tool, "skipped": True, "reason": "missing_required_args", "required": step.get("required", [])})
            continue
        if tool == TOOL_WORKSPACE_LOG_SESSION_EVENT:
            result = workspace_log_session_event(
                workspace_file,
                current_session_id or step.get("example_args", {}).get("session_id", ""),
                step.get("example_args", {}).get("event_type", source or "note"),
                step.get("example_args", {}).get("payload", {"text": text[:2000], "intent": intent}),
            )
        elif tool == TOOL_WORKSPACE_RECORD_CASE:
            result = workspace_record_case(
                workspace_file,
                step.get("example_args", {}).get("task", intent or text[:80] or "memory_execute_write"),
                step.get("example_args", {}).get("projects", projects or []),
                step.get("example_args", {}).get("files", files or []),
                step.get("example_args", {}).get("flow", "memory_write_judge -> memory_plan_write -> memory_execute_write"),
                step.get("example_args", {}).get("risk_points", [text[:120]] if text.strip() else []),
                source_session_id=current_session_id,
                source_task_id=task_id.strip(),
            )
        elif tool == TOOL_WORKSPACE_SUGGEST_CASE:
            result = workspace_suggest_case(workspace_file, current_session_id or step.get("example_args", {}).get("session_id", ""))
        elif tool == TOOL_WORKSPACE_SYNC_CASE_ARTIFACTS:
            result = workspace_sync_case_to_artifacts(
                workspace_file,
                current_session_id or step.get("example_args", {}).get("session_id", ""),
                task_id=step.get("example_args", {}).get("task_id", task_id.strip()),
                title=step.get("example_args", {}).get("title", title.strip()),
            )
        elif tool == TOOL_WORKSPACE_SYNC_SNIFF_ARTIFACTS:
            result = workspace_sync_sniff_to_artifacts(
                workspace_file,
                step.get("example_args", {}).get("intent", intent or text[:80]),
                task_id=step.get("example_args", {}).get("task_id", task_id.strip()),
                title=step.get("example_args", {}).get("title", title.strip()),
            )
        elif tool == TOOL_WORKSPACE_ARTIFACT_UPDATE:
            result = update_artifact(
                workspace_file,
                step.get("example_args", {}).get("name", "workspace_profile"),
                step.get("example_args", {}).get("content", f"## Update\n\n{text[:2000]}"),
            )
        else:
            executed.append({"tool": tool, "skipped": True, "reason": "unsupported_tool"})
            continue
        executed.append({"tool": tool, "result": result})
    return {
        "workspace": plan_result.get("workspace"),
        "memory_layer": plan_result.get("memory_layer"),
        "confidence": plan_result.get("confidence"),
        "judge": plan_result.get("judge"),
        "executed": executed,
        "write_receipts": [item["result"].get("write_receipt") for item in executed if isinstance(item.get("result"), dict) and item["result"].get("write_receipt")],
        "session_id": current_session_id,
    }


def workspace_write_receipts(
    workspace_file: str | Path,
    layer: str = "",
    action: str = "",
    scope: str = "",
    task_id: str = "",
    session_id: str = "",
    limit: int = 50,
) -> Dict[str, Any]:
    config, _ = load_context(workspace_file)
    return {
        "workspace": config.workspace,
        **query_write_receipts(
            str(workspace_file),
            layer=layer,
            action=action,
            scope=scope,
            task_id=task_id,
            session_id=session_id,
            limit=limit,
        ),
    }


def workspace_replay_write_chain(
    workspace_file: str | Path,
    task_id: str = "",
    session_id: str = "",
    limit: int = 100,
) -> Dict[str, Any]:
    config, _ = load_context(workspace_file)
    result = timeline_query(str(workspace_file), task_id=task_id, session_id=session_id, kinds=["write_receipt", "handoff"], limit=limit)
    receipts = result.get("timeline", [])
    timeline = [
        {
            "index": idx + 1,
            "layer": row.get("layer", ""),
            "action": row.get("action", ""),
            "scope": row.get("scope", ""),
            "target": row.get("target", ""),
            "task_id": row.get("task_id", ""),
            "session_id": row.get("session_id", ""),
            "receipt_ref": row.get("receipt_ref", ""),
            "kind": row.get("kind", ""),
            "created_at": row.get("created_at", ""),
        }
        for idx, row in enumerate(receipts)
    ]
    return {
        "workspace": config.workspace,
        "task_id": task_id,
        "session_id": session_id,
        "timeline": timeline,
        "summary": {
            **result.get("summary", {}),
            "timeline_count": len(timeline),
        },
    }


def memory_eval_write_quality(
    workspace_file: str | Path,
    task_id: str = "",
    session_id: str = "",
    intent: str = "",
    limit: int = 100,
) -> Dict[str, Any]:
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
) -> Dict[str, Any]:
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
) -> Dict[str, Any]:
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
) -> Dict[str, Any]:
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
    components = {
        "write_quality": write_eval,
        "resume": resume_eval,
        "handoff": handoff_eval,
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


def workspace_sync_sniff_to_artifacts(
    workspace_file: str | Path,
    intent: str,
    limit: int = 12,
    task_id: str = "",
    title: str = "",
    auto_sync_mode: str = "balanced",
) -> Dict[str, Any]:
    config, _ = load_context(workspace_file)
    sniff = workspace_sniff(workspace_file, intent, limit=limit, auto_sync_mode=auto_sync_mode)
    resolved_task_id = task_id.strip()
    resolved_info = None
    if resolved_task_id:
        resolved_info = {"task_id": resolved_task_id, "created": False}
    else:
        recent_sessions = WorkspaceStore(workspace_file).read_jsonl(SESSION_SUMMARIES_FILE, limit=30)
        resolved_info = resolve_task_space(
            workspace_file,
            intent=intent,
            title=title.strip(),
            create_if_missing=True,
            related_texts=[item.get("task", "") for item in sniff.get("historical_cases", [])] + [item.get("summary", "") or item.get("intent", "") for item in recent_sessions],
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
    update_task_artifact(workspace_file, resolved_task_id, "context", context_content, source="sync_sniff_artifacts")
    update_task_artifact(workspace_file, resolved_task_id, "plan", plan_content, source="sync_sniff_artifacts")
    update_task_artifact(workspace_file, resolved_task_id, "current_summary", summary_content, source="sync_sniff_artifacts")
    touch_task_activity(workspace_file, resolved_task_id, "sync_sniff_artifacts")
    return {
        "workspace": config.workspace,
        "synced": True,
        "intent": intent,
        "task_id": resolved_task_id,
        "task_resolution": resolved_info,
        "updated_artifacts": ["context", "plan", "current_summary"],
        "risk_level": sniff.get("risk_level", "unknown"),
        "source_refs": sniff.get("source_refs", []),
        "memory_layer": "L2_task_space",
        "auto_sync_mode": auto_sync_mode,
        "auto_sync_recommendation": sniff.get("auto_sync_recommendation", {}),
        "write_receipt": build_write_receipt(
            layer=LAYER_L2,
            action=TOOL_WORKSPACE_SYNC_SNIFF_ARTIFACTS,
            scope="task_space",
            target="context,plan,current_summary",
            target_file="artifacts/tasks/*",
            task_id=resolved_task_id,
            updated_artifacts=["context", "plan", "current_summary"],
        ),
    }


def workspace_sync_case_to_artifacts(
    workspace_file: str | Path,
    session_id: str,
    task_id: str = "",
    title: str = "",
    auto_sync_mode: str = "balanced",
) -> Dict[str, Any]:
    config, _ = load_context(workspace_file)
    draft = workspace_suggest_case(workspace_file, session_id)
    if not draft.get("found"):
        return {
            "workspace": config.workspace,
            "session_id": session_id,
            "synced": False,
            "updated_artifacts": [],
            "auto_sync_mode": auto_sync_mode,
            "hint": draft.get("hint", "会话不存在。"),
        }
    case = draft.get("draft_case", {})
    case_risk = _case_risk_profile(case)
    case_risk_level = case_risk["risk_level"]
    resolved_task_id = task_id.strip()
    resolved_info = None
    if resolved_task_id:
        resolved_info = {"task_id": resolved_task_id, "created": False}
    else:
        related_texts = [ref.get("query", "") or ref.get("target", "") for ref in case.get("evidence_refs", [])]
        score_threshold = _score_threshold_for_sync_mode(auto_sync_mode)
        resolved_info = resolve_task_space(
            workspace_file,
            intent=case.get("task", ""),
            title=title.strip() or case.get("task", ""),
            create_if_missing=True,
            related_texts=related_texts,
            score_threshold=score_threshold,
        )
        resolved_task_id = str(resolved_info["task_id"])
    design_content = _merge_artifact_section(
        get_task_artifact(workspace_file, resolved_task_id, "design").get("content", ""),
        "Session Learnings / 会话沉淀",
        _render_case_markdown(case),
    )
    summary_content = _render_task_current_summary_from_case(case, resolved_info or {}, session_id)
    update_task_artifact(workspace_file, resolved_task_id, "design", design_content, source="sync_case_artifacts")
    update_task_artifact(workspace_file, resolved_task_id, "current_summary", summary_content, source="sync_case_artifacts")
    append_task_change_log(workspace_file, resolved_task_id, _render_change_log_entry(case, session_id))
    touch_task_activity(workspace_file, resolved_task_id, "sync_case_artifacts")
    auto_sync = _build_sniff_auto_sync_recommendation(store, resolved_info or {}, case_risk_level, auto_sync_mode=auto_sync_mode)
    return {
        "workspace": config.workspace,
        "session_id": session_id,
        "synced": True,
        "task_id": resolved_task_id,
        "task_resolution": resolved_info,
        "updated_artifacts": ["design", "change_log", "current_summary"],
        "task": case.get("task", ""),
        "risk_level": case_risk_level,
        "risk_evidence": case_risk,
        "source_session_id": case.get("source_session_id", session_id),
        "source_refs": case.get("source_refs", []),
        "memory_layer": "L2_task_space",
        "auto_sync_mode": auto_sync_mode,
        "auto_sync_recommendation": auto_sync,
        "write_receipt": build_write_receipt(
            layer=LAYER_L2,
            action=TOOL_WORKSPACE_SYNC_CASE_ARTIFACTS,
            scope="task_space",
            target="design,change_log,current_summary",
            target_file="artifacts/tasks/*",
            task_id=resolved_task_id,
            session_id=session_id,
            updated_artifacts=["design", "change_log", "current_summary"],
        ),
    }


def _new_session_id() -> str:
    return f"session-{uuid4().hex[:12]}"


def _active_task_summaries(workspace_file: str | Path, limit: int = 5) -> List[Dict[str, Any]]:
    tasks = list_task_spaces(workspace_file, include_archived=False).get("active_tasks", [])
    sorted_tasks = sorted(
        tasks,
        key=lambda item: (
            0 if item.get("status") == "active" else 1,
            -(datetime.fromisoformat(item.get("updated_at", datetime.min.isoformat())).timestamp() if item.get("updated_at") else 0),
            item.get("task_id", ""),
        ),
    )
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
                "last_activity_source": item.get("last_activity_source", ""),
            }
        )
    return rows


def _build_memory_layers(store: WorkspaceStore, active_tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
    refs_count = sum(1 for _ in store.refs_dir.rglob("*") if _.is_file()) if store.refs_dir.exists() else 0
    case_rows = store.read_jsonl("cross-service-task-memory.jsonl", limit=5000)
    current_truth_cases = sum(1 for item in case_rows if item.get("current_truth", True))
    superseded_cases = sum(1 for item in case_rows if item.get("superseded_by"))
    return {
        LAYER_L0: {
            "description": "原始会话事件与外置 payload 引用",
            "event_count": len(store.read_jsonl(SESSION_EVENTS_FILE, limit=5000)),
            "ref_count": refs_count,
        },
        LAYER_L1: {
            "description": "可复用任务经验原子（record-case / suggest-case）",
            "case_count": len(case_rows),
            "current_truth_count": current_truth_cases,
            "superseded_count": superseded_cases,
        },
        LAYER_L2: {
            "description": "任务空间工件（context/plan/design/change-log/current-summary）",
            "active_task_space_count": len(active_tasks),
        },
        LAYER_L3: {
            "description": "工作区协议、规则、拓扑与团队约束",
            "instruction_files": 5,
            "rule_file_count": len(list(store.rules_dir.glob("*.yaml"))),
        },
    }


def _build_memory_overview(memory_layers: Dict[str, Any]) -> Dict[str, Any]:
    l0 = memory_layers.get(LAYER_L0, {})
    l1 = memory_layers.get(LAYER_L1, {})
    l2 = memory_layers.get(LAYER_L2, {})
    l3 = memory_layers.get(LAYER_L3, {})
    return {
        "layer_order": MEMORY_LAYER_ORDER,
        "layer_counts": {
            LAYER_L0: int(l0.get("event_count", 0)),
            LAYER_L1: int(l1.get("case_count", 0)),
            LAYER_L2: int(l2.get("active_task_space_count", 0)),
            LAYER_L3: int(l3.get("rule_file_count", 0)),
        },
        "highlights": [
            f"L0 events={int(l0.get('event_count', 0))}, refs={int(l0.get('ref_count', 0))}",
            f"L1 cases={int(l1.get('case_count', 0))}, current_truth={int(l1.get('current_truth_count', 0))}, superseded={int(l1.get('superseded_count', 0))}",
            f"L2 active_task_spaces={int(l2.get('active_task_space_count', 0))}",
            f"L3 rules={int(l3.get('rule_file_count', 0))}, instructions={int(l3.get('instruction_files', 0))}",
        ],
    }


def _build_write_receipts_overview(store: WorkspaceStore) -> Dict[str, Any]:
    rows = store.read_jsonl(WRITE_RECEIPTS_FILE, limit=5000)
    layers: Dict[str, int] = {}
    actions: Dict[str, int] = {}
    scopes: Dict[str, int] = {}
    for row in rows:
        layer = str(row.get("layer", "") or "")
        action = str(row.get("action", "") or "")
        scope = str(row.get("scope", "") or "")
        if layer:
            layers[layer] = layers.get(layer, 0) + 1
        if action:
            actions[action] = actions.get(action, 0) + 1
        if scope:
            scopes[scope] = scopes.get(scope, 0) + 1
    return {
        "total": len(rows),
        "layer_counts": layers,
        "action_counts": actions,
        "scope_counts": scopes,
        "recent_receipts": rows[-5:],
    }


def _build_continuity_overview(workspace_file: str | Path, active_tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
    resumable = 0
    blocked = 0
    for task in active_tasks:
        if task.get("summary_preview"):
            resumable += 1
        if task.get("status") == "blocked":
            blocked += 1
    return {
        "active_task_count": len(active_tasks),
        "resumable_task_count": resumable,
        "blocked_task_count": blocked,
        "focus_task_id": active_tasks[0].get("task_id", "") if active_tasks else "",
    }


def _infer_task_phase(current_summary: str, timeline: List[Dict[str, Any]]) -> str:
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


def _normalize_model_name(model_name: str) -> str:
    raw = (model_name or "").strip().lower()
    if raw in {"codex", "openai-codex"}:
        return "codex"
    if raw in {"claude", "claude-code", "claudecode"}:
        return "claude-code"
    if raw in {"cursor", "cursor-agent", "cursorai"}:
        return "cursor-agent"
    if raw.startswith("gemini"):
        return "gemini"
    if raw.startswith("deepseek"):
        return "deepseek"
    if raw.startswith("glm") or raw.startswith("chatglm"):
        return "glm"
    if raw.startswith("qwen"):
        return "qwen"
    if raw.startswith("minimax"):
        return "minimax"
    if raw.startswith("mimo"):
        return "mimo"
    return "generic-mcp-agent"


def _load_resume_rules(store: WorkspaceStore, text: str) -> Dict[str, Any]:
    data = load_yaml_rule_config(store, "resume-rules.yaml", DEFAULT_RESUME_RULES)
    default = dict(DEFAULT_RESUME_RULES.get("default", {}))
    default.update(data.get("default", {}))
    normalized = (text or "").lower()
    for profile_name, profile in (data.get("profiles", {}) or {}).items():
        triggers = [str(item).lower() for item in profile.get("trigger_keywords", [])]
        if triggers and any(token in normalized for token in triggers):
            merged = dict(default)
            merged.update(profile)
            merged["profile_name"] = profile_name
            return merged
    default["profile_name"] = "default"
    return default


def _load_handoff_rules(store: WorkspaceStore, normalized_model: str) -> Dict[str, Any]:
    data = load_yaml_rule_config(store, "handoff-rules.yaml", DEFAULT_HANDOFF_RULES)
    default = dict(DEFAULT_HANDOFF_RULES.get("default", {}))
    default.update(data.get("default", {}))
    for profile_name, profile in (data.get("profiles", {}) or {}).items():
        trigger_models = [str(item).lower() for item in profile.get("trigger_models", [])]
        if trigger_models and normalized_model in trigger_models:
            merged = dict(default)
            merged.update(profile)
            merged["profile_name"] = profile_name
            return merged
    default["profile_name"] = "default"
    return default


def _load_write_policy_rules(store: WorkspaceStore) -> Dict[str, Any]:
    return load_yaml_rule_config(store, "write-policy-rules.yaml", DEFAULT_WRITE_POLICY_RULES).get("default", {})


def _load_auto_sync_rules(store: WorkspaceStore) -> Dict[str, Any]:
    return load_yaml_rule_config(store, "auto-sync-rules.yaml", DEFAULT_AUTO_SYNC_RULES).get("default", {})


def _load_eval_rules(store: WorkspaceStore) -> Dict[str, Any]:
    return load_yaml_rule_config(store, "eval-rules.yaml", DEFAULT_EVAL_RULES)


def _build_core_memory_blocks_status(store: WorkspaceStore) -> Dict[str, Any]:
    blocks = []
    filled_count = 0
    for key, filename in CORE_MEMORY_BLOCKS.items():
        content = store.read_artifact(filename, "")
        has_custom_content = "## Content" in content and "Fill" not in content.split("## Content", 1)[1]
        if has_custom_content:
            filled_count += 1
        blocks.append(
            {
                "name": key,
                "file": filename,
                "exists": store.artifact_exists(filename),
                "filled": has_custom_content,
                "preview": content.splitlines()[:4],
            }
        )
    return {
        "block_count": len(blocks),
        "filled_count": filled_count,
        "blocks": blocks,
    }


def _choose_l3_artifact_name(text: str) -> str:
    normalized = (text or "").lower()
    if any(k in normalized for k in ["团队", "协作", "code review", "评审", "规范", "rules", "约定"]):
        return "team_rules"
    if any(k in normalized for k in ["架构", "invariant", "分层", "模块边界", "边界", "design principle"]):
        return "architecture_invariants"
    if any(k in normalized for k in ["迁移", "migration", "cutover", "灰度", "兼容期"]):
        return "active_migration_policy"
    return "workspace_profile"


def _build_focus_reason(task: Dict[str, Any]) -> str:
    parts = []
    status = str(task.get("status", "")).strip().lower()
    if status == "active":
        parts.append("状态为 active")
    priority = str(task.get("priority", "")).strip().lower()
    if priority in {"high", "critical"}:
        parts.append(f"优先级 {priority}")
    source = str(task.get("last_activity_source", "")).strip()
    if source:
        parts.append(f"最近活动来源 {source}")
    updated_at = str(task.get("updated_at", "")).strip()
    if updated_at:
        parts.append(f"最近更新时间 {updated_at}")
    return "；".join(parts) if parts else "按任务状态与最近活动综合排序。"


def _is_compact_view(view: str) -> bool:
    return (view or "").strip().lower() == "compact"


def _compact_task_rows(rows: List[Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
    return [
        {
            "task_id": row.get("task_id", ""),
            "title": row.get("title", ""),
            "status": row.get("status", ""),
            "priority": row.get("priority", ""),
            "updated_at": row.get("updated_at", ""),
            "summary_preview": row.get("summary_preview", ""),
        }
        for row in rows[:limit]
    ]


def _compact_sniff_result(result: Dict[str, Any]) -> Dict[str, Any]:
    symbolic = result.get("symbolic_context", {}) or {}
    focus_entities = symbolic.get("focus_entities", {}) or {}
    return {
        "workspace": result.get("workspace", ""),
        "intent": result.get("intent", ""),
        "risk_level": result.get("risk_level", ""),
        "matched_services": result.get("matched_services", [])[:5],
        "candidate_files": [
            {"project": item.get("project", ""), "path": item.get("path", ""), "score": item.get("score", 0)}
            for item in result.get("candidate_files", [])[:5]
        ],
        "related_summary": {
            "api_count": len(result.get("related_apis", []) or []),
            "feign_count": len(result.get("related_feigns", []) or []),
            "mq_count": len(result.get("related_mq", []) or []),
            "rule_count": len(result.get("related_rules", []) or []),
            "case_count": len(result.get("historical_cases", []) or []),
        },
        "task_candidates": [
            {
                "task_id": item.get("task_id", ""),
                "title": item.get("title", ""),
                "status": item.get("status", ""),
                "score": item.get("score", 0),
            }
            for item in result.get("task_candidates", [])[:2]
        ],
        "source_refs": result.get("source_refs", [])[:5],
        "resolved_task": result.get("resolved_task", {}),
        "auto_sync_recommendation": result.get("auto_sync_recommendation", {}),
        "write_judge_recommendation": result.get("write_judge_recommendation", {}),
        "lookup_hint": result.get("lookup_hint", {}),
        "symbolic_context": {
            "flow_flags": symbolic.get("flow_flags", {}),
            "flow_mermaid": symbolic.get("flow_mermaid", ""),
            "focus_entities": {
                "services": focus_entities.get("services", [])[:3],
                "files": focus_entities.get("files", [])[:4],
                "apis": focus_entities.get("apis", [])[:3],
                "feigns": focus_entities.get("feigns", [])[:3],
            },
        },
        "next_steps": result.get("next_steps", [])[:4],
    }


def _compact_workspace_status(result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "workspace": result.get("workspace", ""),
        "root": result.get("root", ""),
        "index_counts": result.get("index_counts", {}),
        "semantic_index": result.get("semantic_index", {}),
        "memory_layers": result.get("memory_layers", {}),
        "memory_overview": result.get("memory_overview", {}),
        "write_receipts_overview": {
            "total": (result.get("write_receipts_overview", {}) or {}).get("total", 0),
            "layer_counts": (result.get("write_receipts_overview", {}) or {}).get("layer_counts", {}),
            "action_counts": (result.get("write_receipts_overview", {}) or {}).get("action_counts", {}),
        },
        "continuity_overview": result.get("continuity_overview", {}),
        "core_memory_blocks": {
            "block_count": (result.get("core_memory_blocks", {}) or {}).get("block_count", 0),
            "filled_count": (result.get("core_memory_blocks", {}) or {}).get("filled_count", 0),
        },
        "active_task_spaces": _compact_task_rows(result.get("active_task_spaces", []), limit=5),
        "current_focus_task": result.get("current_focus_task", {}),
    }


def _compact_resume_packet(result: Dict[str, Any]) -> Dict[str, Any]:
    return with_schema(
        "resume_packet",
        {
            "workspace": result.get("workspace", ""),
            "task_id": result.get("task_id", ""),
            "task_title": result.get("task_title", ""),
            "task_status": result.get("task_status", ""),
            "current_phase": result.get("current_phase", ""),
            "current_summary": _trim_summary(str(result.get("current_summary", "") or "")),
            "next_recommended_actions": result.get("next_recommended_actions", [])[:3],
            "unresolved_items": result.get("unresolved_items", [])[:3],
            "verification_pending": result.get("verification_pending", False),
            "resume_rule_profile": result.get("resume_rule_profile", ""),
        },
    )


def _compact_continuity_dashboard(result: Dict[str, Any]) -> Dict[str, Any]:
    resume_packet = result.get("resume_packet", {}) or {}
    return with_schema(
        "workspace_continuity_dashboard",
        {
            "workspace": result.get("workspace", ""),
            "focus_task": result.get("focus_task", {}),
            "continuity_overview": result.get("continuity_overview", {}),
            "resume_packet": {
                "task_id": resume_packet.get("task_id", ""),
                "task_title": resume_packet.get("task_title", ""),
                "current_phase": resume_packet.get("current_phase", ""),
                "resume_rule_profile": resume_packet.get("resume_rule_profile", ""),
                "next_recommended_actions": resume_packet.get("next_recommended_actions", [])[:3],
                "unresolved_items": resume_packet.get("unresolved_items", [])[:3],
            },
            "next_actions": result.get("next_actions", [])[:3],
            "unresolved_items": result.get("unresolved_items", [])[:3],
            "recent_receipts": result.get("recent_receipts", [])[:3],
            "recent_handoffs": result.get("recent_handoffs", [])[:3],
            "recent_evidence": result.get("recent_evidence", [])[:3],
        },
    )


def _compact_workspace_dashboard(result: Dict[str, Any]) -> Dict[str, Any]:
    focus_dashboard = result.get("focus_dashboard", {}) or {}
    focus_resume_eval = result.get("focus_resume_eval", {}) or {}
    tool_usage_report = result.get("tool_usage_report", {}) or {}
    write_receipts_overview = result.get("write_receipts_overview", {}) or {}
    return with_schema(
        "workspace_dashboard",
        {
            "workspace": result.get("workspace", ""),
            "focus_task": result.get("focus_task", {}),
            "continuity_overview": result.get("continuity_overview", {}),
            "write_receipts_overview": {
                "total": write_receipts_overview.get("total", 0),
                "layer_counts": write_receipts_overview.get("layer_counts", {}),
                "action_counts": write_receipts_overview.get("action_counts", {}),
            },
            "active_tasks": _compact_task_rows(result.get("active_tasks", []), limit=5),
            "resumable_tasks": _compact_task_rows(result.get("resumable_tasks", []), limit=5),
            "blocked_tasks": _compact_task_rows(result.get("blocked_tasks", []), limit=5),
            "low_quality_tasks": _compact_task_rows(result.get("low_quality_tasks", []), limit=5),
            "recent_receipts": result.get("recent_receipts", [])[:3],
            "recent_handoffs": result.get("recent_handoffs", [])[:3],
            "focus_dashboard": {
                "focus_task": focus_dashboard.get("focus_task", {}),
                "next_actions": focus_dashboard.get("next_actions", [])[:3],
                "unresolved_items": focus_dashboard.get("unresolved_items", [])[:3],
            },
            "focus_resume_eval": {
                "quality": focus_resume_eval.get("quality", ""),
                "score": focus_resume_eval.get("score", 0),
                "findings": focus_resume_eval.get("findings", [])[:3],
            },
            "tool_usage_report": {
                "summary": tool_usage_report.get("summary", {}),
                "lookup_tool_counts": tool_usage_report.get("lookup_tool_counts", {}),
                "suspected_bypass": tool_usage_report.get("suspected_bypass", [])[:3],
                "adoption_hints": tool_usage_report.get("adoption_hints", [])[:2],
            },
        },
    )


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


def _build_sniff_auto_sync_recommendation(
    store: WorkspaceStore,
    task_resolution: Dict[str, Any],
    risk_level: str,
    auto_sync_mode: str = "balanced",
) -> Dict[str, Any]:
    policy = _load_auto_sync_rules(store)
    aliases = policy.get("mode_aliases", {}) or {}
    raw_mode = (auto_sync_mode or "balanced").strip().lower()
    mode = str(aliases.get(raw_mode, raw_mode) or "balanced")
    modes = policy.get("modes", {}) or {}
    if mode not in modes:
        mode = "balanced"
    mode_policy = modes.get(mode, {})
    resolved = bool(task_resolution.get("resolved"))
    task_id = str(task_resolution.get("task_id", "") or "")
    score = int(task_resolution.get("score", 0) or 0)
    score_threshold = int(task_resolution.get("score_threshold", 3) or 3)
    candidates = task_resolution.get("candidates", []) or []
    recommendation = {
        "recommended": False,
        "confidence": "low",
        "task_id": task_id if resolved else "",
        "score": score,
        "score_threshold": score_threshold,
        "reason": "",
        "mode": mode,
        "fallback": str(mode_policy.get("fallback", "未满足自动同步条件时，建议先人工确认 task_candidates 再同步。")),
    }
    if not resolved or not task_id:
        recommendation["reason"] = "未命中明确任务空间，建议先人工确认候选任务。"
        return recommendation

    delta = score - score_threshold
    allowed_risks = {str(item) for item in mode_policy.get("allowed_risk_levels", [])}
    min_delta = int(mode_policy.get("min_delta", 0) or 0)

    if delta >= 2:
        recommendation["recommended"] = True
        recommendation["confidence"] = "high"
        recommendation["reason"] = "匹配分数明显高于阈值，可自动同步到已命中任务空间。"
        return recommendation

    if delta >= min_delta and risk_level in allowed_risks:
        recommendation["recommended"] = True
        recommendation["confidence"] = "high" if mode == "strict" else "medium"
        recommendation["reason"] = f"{mode} 模式命中 auto-sync-rules 条件，建议自动同步。"
        return recommendation

    recommendation["confidence"] = "medium" if delta >= 0 else "low"
    if risk_level == "high":
        recommendation["reason"] = "当前风险等级较高，建议先人工确认再同步。"
    else:
        recommendation["reason"] = "匹配分数接近阈值，建议优先确认候选任务。"
    if candidates:
        recommendation["fallback"] = "可优先检查 task_candidates[0] 的 match_reasons，再决定是否同步。"
    return recommendation


def _score_threshold_for_sync_mode(auto_sync_mode: str) -> int:
    mode = (auto_sync_mode or "balanced").strip().lower()
    if mode == "strict":
        return 4
    if mode == "aggressive":
        return 1
    return 3


def _case_risk_level(case: Dict[str, Any]) -> str:
    return _case_risk_profile(case)["risk_level"]


def _case_risk_profile(case: Dict[str, Any]) -> Dict[str, Any]:
    risk_points = case.get("risk_points", [])
    refs = case.get("evidence_refs", []) if isinstance(case.get("evidence_refs", []), list) else []

    score = 0
    matched_signals: List[str] = []
    point_text = json.dumps(risk_points, ensure_ascii=False).lower()
    for token, weight, label in [
        ("contract", 3, "risk_points:contract"),
        ("feign", 3, "risk_points:feign"),
        ("mq", 3, "risk_points:mq"),
        ("topic", 2, "risk_points:topic"),
        ("dto", 2, "risk_points:dto"),
        ("config", 2, "risk_points:config"),
        ("兼容", 3, "risk_points:compatibility"),
        ("breaking", 3, "risk_points:breaking"),
    ]:
        if token in point_text:
            score += weight
            matched_signals.append(label)

    high_ref_types = {"contract", "mq", "dto", "config"}
    medium_ref_types = {"impact", "cross_service", "symbol"}
    counted_ref_types: Dict[str, int] = {}
    for ref in refs:
        ref_type = _classify_case_evidence_ref(ref)
        counted_ref_types[ref_type] = counted_ref_types.get(ref_type, 0) + 1
        if ref_type in high_ref_types:
            score += 2
            matched_signals.append(f"evidence:{ref_type}")
        elif ref_type in medium_ref_types:
            score += 1
            matched_signals.append(f"evidence:{ref_type}")

    if score >= 5:
        level = "high"
    elif score >= 2:
        level = "medium"
    else:
        level = "low"

    return {
        "risk_level": level,
        "score": score,
        "signals": matched_signals[:20],
        "evidence_type_counts": counted_ref_types,
    }


def _classify_case_evidence_ref(ref: Dict[str, Any]) -> str:
    haystack = json.dumps(ref, ensure_ascii=False).lower()
    tool_name = str(ref.get("tool_name", "")).lower()
    event_type = str(ref.get("event_type", "")).lower()

    if any(mark in tool_name for mark in ["check_contract", "contract"]) or any(mark in haystack for mark in ["feign", "contract", "endpoint"]):
        return "contract"
    if any(mark in haystack for mark in ["kafka", "rocketmq", "mq", "topic", "consumer"]):
        return "mq"
    if any(mark in haystack for mark in ["dto", "request", "response", "field"]):
        return "dto"
    if any(mark in haystack for mark in ["application.yml", "bootstrap.yml", "config", "nacos"]):
        return "config"
    if any(mark in tool_name for mark in ["impact", "plan_change"]):
        return "impact"
    if "tool_call" in event_type and any(mark in haystack for mark in ["service", "client"]):
        return "cross_service"
    if any(mark in tool_name for mark in ["symbol", "query", "context", "callers", "callees"]):
        return "symbol"
    return "other"


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
    words = base_tokenize(text)
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
        repo = config.resolve_service_path(svc)
        if not (repo / ".git").exists():
            continue
        cmd = ["git", "diff", "--name-only"]
        if scope == "staged":
            cmd = ["git", "diff", "--name-only", "--cached"]
        elif scope == "head":
            cmd = ["git", "diff", "--name-only", "HEAD~1..HEAD"]
        try:
            out = subprocess.check_output(cmd, cwd=repo, text=True, stderr=subprocess.DEVNULL)
            changed.extend(
                [
                    f"{config.service_logical_prefix(svc)}/{line.strip()}".strip("/")
                    for line in out.splitlines()
                    if line.strip()
                ]
            )
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


def _prepare_session_event_payload(
    store: WorkspaceStore,
    session_id: str,
    event_type: str,
    payload: Dict[str, Any],
) -> tuple[Dict[str, Any], str, int]:
    safe_payload = payload if isinstance(payload, dict) else {}
    payload_bytes = len(json.dumps(safe_payload, ensure_ascii=False).encode("utf-8"))
    if payload_bytes <= EVENT_PAYLOAD_INLINE_LIMIT:
        return safe_payload, "", payload_bytes
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    ref_name = f"refs/sessions/{session_id}/{timestamp}-{event_type}.json"
    payload_ref = store.write_memory_ref_json(ref_name, safe_payload)
    compact = _compact_session_payload(safe_payload)
    compact["_payload_offloaded"] = True
    compact["_payload_ref"] = payload_ref
    compact["_payload_keys"] = sorted(safe_payload.keys())[:20]
    compact["_payload_bytes"] = payload_bytes
    return compact, payload_ref, payload_bytes


def _compact_session_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    compact: Dict[str, Any] = {}
    preferred_keys = [
        "tool_name",
        "query",
        "target",
        "name",
        "project",
        "file",
        "file_path",
        "path",
        "intent",
        "outcome",
        "text",
        "summary",
        "note",
    ]
    for key in preferred_keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            compact[key] = value[:300]
        elif isinstance(value, (int, float, bool)):
            compact[key] = value
    if "verified_by" in payload and isinstance(payload.get("verified_by"), list):
        compact["verified_by"] = payload.get("verified_by", [])[:10]
    return compact


def _build_case_evidence_refs(events: List[Dict[str, Any]], limit: int = 12) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    for idx, event in enumerate(events[-limit:], start=max(len(events) - limit, 0) + 1):
        payload = _event_payload(event)
        ref = {
            "event_index": idx,
            "event_type": event.get("event_type", ""),
            "created_at": event.get("created_at", ""),
        }
        payload_ref = event.get("payload_ref", "")
        if isinstance(payload_ref, str) and payload_ref:
            ref["payload_ref"] = payload_ref
        for key in ["tool_name", "query", "target", "name", "project", "file_path", "path"]:
            value = payload.get(key)
            if isinstance(value, str) and value:
                ref[key] = value
        refs.append(ref)
    return refs


def _build_event_source_refs(events: List[Dict[str, Any]], limit: int = 20) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    for event in events[-limit:]:
        payload = _event_payload(event)
        event_type = str(event.get("event_type", "") or "")
        payload_ref = str(event.get("payload_ref", "") or "")
        entry = {
            "type": "session_event",
            "event_type": event_type,
            "created_at": event.get("created_at", ""),
        }
        for key in ["tool_name", "query", "target", "project", "file_path", "path"]:
            value = payload.get(key)
            if isinstance(value, str) and value:
                entry[key] = value
        if payload_ref:
            entry["payload_ref"] = payload_ref
        if len(entry) > 3:
            refs.append(entry)
    return refs


def _build_sniff_source_refs(
    matched_files: List[Dict[str, Any]],
    related_feigns: List[Dict[str, Any]],
    related_apis: List[Dict[str, Any]],
    related_mq: List[Dict[str, Any]],
    related_cases: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    for item in matched_files[:6]:
        path = item.get("path", "")
        if path:
            refs.append({"type": "file", "path": path, "project": item.get("project", ""), "score": item.get("score", 0)})
    for item in related_feigns[:4]:
        if item.get("interface"):
            refs.append({"type": "feign", "name": item.get("interface", ""), "project": item.get("project", ""), "path": item.get("file", "")})
    for item in related_apis[:4]:
        if item.get("path"):
            refs.append({"type": "api", "name": f"{item.get('http_method', '')} {item.get('path', '')}".strip(), "project": item.get("project", ""), "path": item.get("file", "")})
    for item in related_mq[:4]:
        if item.get("topic"):
            refs.append({"type": "mq", "name": item.get("topic", ""), "project": item.get("project", ""), "path": item.get("file", "")})
    for item in related_cases[-3:]:
        if item.get("task"):
            refs.append({"type": "case", "task": item.get("task", ""), "created_at": item.get("created_at", "")})
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
    lines.append("")
    lines.append("### Source Refs")
    lines.extend(
        [
            f"- [{item.get('type', '')}] {item.get('name', '') or item.get('task', '') or item.get('path', '')}"
            for item in sniff.get("source_refs", [])[:10]
        ]
        or ["- None"]
    )
    return "\n".join(lines)


def _render_sniff_plan_markdown(sniff: Dict[str, Any]) -> str:
    lines = [
        f"- Intent: {sniff.get('intent', '')}",
        "",
        "### Next Steps",
    ]
    lines.extend([f"- {item}" for item in sniff.get("next_steps", [])] or ["- None"])
    lines.append("")
    lines.append("### Source Refs")
    lines.extend(
        [
            f"- [{item.get('type', '')}] {item.get('name', '') or item.get('task', '') or item.get('path', '')}"
            for item in sniff.get("source_refs", [])[:10]
        ]
        or ["- None"]
    )
    return "\n".join(lines)


def _render_case_markdown(case: Dict[str, Any]) -> str:
    lines = [
        f"- Task: {case.get('task', '')}",
        f"- Projects: {', '.join(case.get('projects', []))}",
        f"- Flow: {case.get('flow', '')}",
        f"- Memory layer: {case.get('memory_layer', 'L1_case_atom')}",
        f"- Source session: {case.get('source_session_id', '') or 'None'}",
        "",
        "### Risk Points",
    ]
    lines.extend([f"- {item}" for item in case.get("risk_points", [])] or ["- None"])
    lines.append("")
    lines.append("### Source Refs")
    lines.extend(
        [
            f"- [{item.get('type', '')}] {item.get('tool_name', '') or item.get('query', '') or item.get('target', '') or item.get('file_path', '') or item.get('payload_ref', '')}"
            for item in case.get("source_refs", [])[:10]
        ]
        or ["- None"]
    )
    lines.append("")
    lines.append("### Evidence Refs")
    lines.extend(
        [
            f"- [{item.get('event_type', '')}] {item.get('tool_name', '') or item.get('query', '') or item.get('target', '')}"
            + (f" (payload_ref: {item.get('payload_ref', '')})" if item.get("payload_ref") else "")
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
    source_ref_names = ", ".join(
        item.get("name", "") or item.get("task", "") or Path(item.get("path", "")).name
        for item in sniff.get("source_refs", [])[:3]
    ) or "None"
    source_ref_types = ", ".join(item.get("type", "") for item in sniff.get("source_refs", [])[:5]) or "None"
    return (
        "# Current Summary / 当前最短上下文\n\n"
        f"- Intent: {sniff.get('intent', '')}\n"
        f"- Memory layer: L2_task_space\n"
        f"- Risk level: {sniff.get('risk_level', 'unknown')}\n"
        f"- Resolved task: {resolved_info.get('title', resolved_info.get('task_id', ''))}\n"
        f"- Services: {services}\n"
        f"- Top files: {top_files}\n\n"
        f"- Source ref types: {source_ref_types}\n"
        f"- Source ref highlights: {source_ref_names}\n\n"
        "## Next Steps\n\n"
        f"{next_steps}\n"
    )


def _render_task_current_summary_from_case(case: Dict[str, Any], resolved_info: Dict[str, Any], session_id: str) -> str:
    risk_points = ", ".join(case.get("risk_points", [])[:4]) or "None"
    projects = ", ".join(case.get("projects", [])[:6]) or "None"
    payload_ref_count = sum(1 for item in case.get("evidence_refs", []) if item.get("payload_ref"))
    return (
        "# Current Summary / 当前最短上下文\n\n"
        f"- Task: {case.get('task', '')}\n"
        f"- Session: {session_id}\n"
        f"- Memory layer: {case.get('memory_layer', 'L1_case_atom')}\n"
        f"- Resolved task: {resolved_info.get('title', resolved_info.get('task_id', ''))}\n"
        f"- Projects: {projects}\n"
        f"- Flow: {case.get('flow', '')}\n"
        f"- Risk points: {risk_points}\n"
        f"- Source refs: {len(case.get('source_refs', []))}\n"
        f"- Evidence refs with payload_ref: {payload_ref_count}\n"
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
    flow_lines.extend(
        [
            '  E --> S["workspace_end_session"]',
            '  S --> Y["workspace_sync_case_artifacts"]',
            '  Y --> W["workspace_record_case"]',
        ]
    )
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
