"""Workspace status, sniff, trace, lookup_hint, and dashboard functions."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from ..artifacts import (
    CORE_MEMORY_BLOCKS,
    get_task_artifact,
    list_task_spaces,
    resolve_task_space,
)
from ..rules import match_rules
from ..schemas import with_schema
from ..semantic import semantic_index_stats
from ..store import WorkspaceStore
from ..workspace_shape import analyze_workspace_shape
from ..verification.heuristics import apply_candidate_path_learning
from ..write_receipts import WRITE_RECEIPTS_FILE
from .common import (
    LAYER_L0,
    LAYER_L1,
    LAYER_L2,
    LAYER_L3,
    MEMORY_LAYER_ORDER,
    SESSION_EVENTS_FILE,
    SESSION_SUMMARIES_FILE,
    TOOL_WORKSPACE_LOG_SESSION_EVENT,
    TOOL_WORKSPACE_SYNC_CASE_ARTIFACTS,
    TOOL_WORKSPACE_SYNC_SNIFF_ARTIFACTS,
    _build_sniff_auto_sync_recommendation,
    _build_sniff_source_refs,
    _is_compact_view,
    _sniff_risk_level,
    _trim_summary,
    load_context,
    tokenize,
    rank_files,
)
from .compact import (
    _compact_continuity_dashboard,
    _compact_sniff_result,
    _compact_workspace_dashboard,
    _compact_workspace_status,
    _measure_compact_gain,
)
from .session import workspace_recent_evidence
from .write import memory_write_judge, workspace_write_receipts
from .query import memory_tool_usage_report
from ..tracking import log_token_gain


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def workspace_status(workspace_file: str | Path, view: str = "compact", budget: str = "medium") -> Dict[str, Any]:
    config, store = load_context(workspace_file)
    workspace_shape = analyze_workspace_shape(config)
    active_tasks = _active_task_summaries(workspace_file, limit=5)
    current_focus_task = dict(active_tasks[0]) if active_tasks else None
    memory_layers = _build_memory_layers(config, store, active_tasks)
    core_memory_blocks = _build_core_memory_blocks_status(store)
    if current_focus_task:
        current_focus_task["focus_reason"] = _build_focus_reason(current_focus_task)
    result = {
        "workspace": config.workspace,
        "root": str(config.root_path),
        "services": [s.__dict__ for s in config.services],
        "workspace_shape": workspace_shape,
        "workspace_warnings": workspace_shape.get("warnings", []),
        "index_counts": {
            "files": len(store.read_json_prefer_backend("file-index.json", [])),
            "symbols": len(store.read_json_prefer_backend("java-symbol-index.json", [])),
            "apis": len(store.read_json_prefer_backend("api-index.json", [])),
            "feigns": len(store.read_json_prefer_backend("feign-index.json", [])),
            "mq": len(store.read_json_prefer_backend("mq-index.json", [])),
            "cases": len(store.read_jsonl_prefer_backend("cross-service-task-memory.jsonl", limit=1000)),
            "session_events": len(store.read_jsonl_prefer_backend(SESSION_EVENTS_FILE, limit=5000)),
            "session_summaries": len(store.read_jsonl_prefer_backend(SESSION_SUMMARIES_FILE, limit=1000)),
            "semantic_docs": semantic_index_stats(workspace_file).get("doc_count", 0),
        },
        "semantic_index": semantic_index_stats(workspace_file),
        "memory_layers": memory_layers,
        "memory_overview": _build_memory_overview(memory_layers),
        "memory_backend": store.memory_backend_stats(),
        "write_receipts_overview": _build_write_receipts_overview(store),
        "continuity_overview": _build_continuity_overview(workspace_file, active_tasks),
        "core_memory_blocks": core_memory_blocks,
        "active_task_spaces": active_tasks,
        "current_focus_task": current_focus_task,
        "topology": store.read_json_prefer_backend("service-topology.json", {}),
    }
    if _is_compact_view(view):
        compact = _compact_workspace_status(result, budget=budget)
        gain = _measure_compact_gain(result, compact)
        log_token_gain(workspace_file, "workspace_status", budget=budget, model="", raw_tokens=gain["raw_tokens"], compact_tokens=gain["compact_tokens"], view=view)
        return compact
    return result


def workspace_sniff(
    workspace_file: str | Path,
    intent: str,
    limit: int = 12,
    auto_sync_mode: str = "balanced",
    include_lookup_hint: bool = True,
    view: str = "compact",
    budget: str = "medium",
) -> Dict[str, Any]:
    config, store = load_context(workspace_file)
    file_index = store.read_json_prefer_backend("file-index.json", [])
    symbols = store.read_json_prefer_backend("java-symbol-index.json", [])
    apis = store.read_json_prefer_backend("api-index.json", [])
    feigns = store.read_json_prefer_backend("feign-index.json", [])
    mq = store.read_json_prefer_backend("mq-index.json", [])
    cases = store.read_jsonl_prefer_backend("cross-service-task-memory.jsonl", limit=200)

    keywords = tokenize(intent)
    matched_files = rank_files(file_index, symbols, keywords)[:limit]
    matched_services = sorted({item["project"] for item in matched_files})
    related_apis = [x for x in apis if any(k in json.dumps(x, ensure_ascii=False).lower() for k in keywords)][:limit]
    related_feigns = [x for x in feigns if any(k in json.dumps(x, ensure_ascii=False).lower() for k in keywords)][:limit]
    related_mq = [x for x in mq if any(k in json.dumps(x, ensure_ascii=False).lower() for k in keywords)][:limit]
    related_cases = [x for x in cases if any(k in json.dumps(x, ensure_ascii=False).lower() for k in keywords)][-5:]
    recent_sessions = store.read_jsonl_prefer_backend(SESSION_SUMMARIES_FILE, limit=30)
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
    candidate_paths = _build_sniff_candidate_paths(
        intent=intent,
        risk_level=sniff_risk_level,
        lookup_hint=lookup_hint or {},
        task_resolution=task_resolution,
        auto_sync=auto_sync,
        write_judge_decision=write_judge_recommendation.get("decision", {}),
        matched_files=matched_files,
        related_apis=related_apis,
        related_feigns=related_feigns,
        related_mq=related_mq,
    )
    candidate_paths = apply_candidate_path_learning(workspace_file, candidate_paths)
    recommended_path = dict(candidate_paths[0]) if candidate_paths else {}

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
        "candidate_paths": candidate_paths,
        "recommended_path": recommended_path,
        "symbolic_context": _build_sniff_symbolic_context(intent, sniff_risk_level, matched_services, matched_files, related_feigns, related_apis, related_mq, related_cases),
        "next_steps": [
            '先用 mc_lookup(query="...", mode="code") 缩小入口范围，再用 mc_lookup(query="...", mode="symbol") 定位关键符号',
            '对关键符号用 mc_lookup(query="...", mode="chain", chain_direction="callers/callees") 理清上下游调用链',
            '先用 mc_admin(action="write_judge") / mc_admin(action="write_plan") 判断信息应写入 L0/L1/L2/L3，再执行对应写入',
            '如果这是持续任务或多人协作任务，用 mc_sync(intent="...", auto_sync_mode="balanced") 把 context/plan 写入任务空间',
            '改动前用 mc_analyze(target="...", depth="standard/full") 明确风险与验证项',
            '如果涉及 DTO/Feign/MQ Message，用 mc_analyze(target="...", depth="full", contract_file="...")',
            '长任务建议用 mc_admin(action="session_log", ...) 记录关键步骤，结束后用 mc_close(session_id="...", record_case=True) 沉淀案例',
        ],
    }
    if _is_compact_view(view):
        compact = _compact_sniff_result(result, budget=budget)
        gain = _measure_compact_gain(result, compact)
        log_token_gain(workspace_file, "workspace_sniff", budget=budget, model="", raw_tokens=gain["raw_tokens"], compact_tokens=gain["compact_tokens"], view=view)
        return compact
    return result


def workspace_trace(workspace_file: str | Path, entry: str) -> Dict[str, Any]:
    _, store = load_context(workspace_file)
    topology = store.read_json_prefer_backend("service-topology.json", {})
    apis = store.read_json_prefer_backend("api-index.json", [])
    feigns = store.read_json_prefer_backend("feign-index.json", [])
    mq = store.read_json_prefer_backend("mq-index.json", [])
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
    config, store = load_context(workspace_file)
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
    candidate_paths = _build_lookup_hint_candidate_paths(
        recommended_path=recommended_path,
        preferred_tools=preferred_tools,
        reasons=reasons,
        sniff=sniff,
    )
    candidate_paths = apply_candidate_path_learning(workspace_file, candidate_paths)
    return with_schema(
        "lookup_hint",
        {
            "workspace": config.workspace,
            "query": query,
            "intent": intent,
            "recommended_path": recommended_path,
            "recommended_candidate_path": dict(candidate_paths[0]) if candidate_paths else {},
            "candidate_paths": candidate_paths,
            "preferred_tools": preferred_tools,
            "reasons": reasons,
            "should_use_memory_center": should_use_memory_center,
            "sniff_risk_level": sniff.get("risk_level", ""),
            "matched_services": sniff.get("matched_services", [])[:5],
            "candidate_files": sniff.get("candidate_files", [])[:5],
            "fallback": "若推荐结果不足以定位，再退回本地 grep / rg 做小范围确认。",
        },
    )


def workspace_dashboard(
    workspace_file: str | Path,
    intent: str = "",
    limit: int = 10,
    view: str = "compact",
    budget: str = "medium",
) -> Dict[str, Any]:
    # Lazy import to avoid circular dependency with .resume and .eval
    from .resume import workspace_resume_packet, workspace_next_actions, workspace_unresolved_items, workspace_handoff_history
    from .eval import memory_eval_write_quality, memory_eval_resume

    from ..timeline import timeline_query

    status = workspace_status(workspace_file, view="full", budget=budget)
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
        workspace_continuity_dashboard(
            workspace_file,
            intent=intent,
            task_id=(focus_task or {}).get("task_id", ""),
            limit=min(limit, 5),
            view=view,
            budget=budget,
        )
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
    if _is_compact_view(view):
        compact = _compact_workspace_dashboard(result, budget=budget)
        gain = _measure_compact_gain(result, compact)
        log_token_gain(workspace_file, "workspace_dashboard", budget=budget, model="", raw_tokens=gain["raw_tokens"], compact_tokens=gain["compact_tokens"], view=view)
        return compact
    return result


def workspace_continuity_dashboard(
    workspace_file: str | Path,
    intent: str = "",
    task_id: str = "",
    session_id: str = "",
    limit: int = 10,
    view: str = "compact",
    budget: str = "medium",
) -> Dict[str, Any]:
    # Lazy import to avoid circular dependency with .resume
    from .resume import workspace_resume_packet, workspace_next_actions, workspace_unresolved_items, workspace_handoff_history

    status = workspace_status(workspace_file, view="compact", budget=budget)
    focus_task_id = task_id or (status.get("current_focus_task") or {}).get("task_id", "")
    resume_packet = workspace_resume_packet(workspace_file, task_id=focus_task_id, session_id=session_id, intent=intent, limit=limit, view=view, budget=budget)
    next_actions = workspace_next_actions(workspace_file, task_id=focus_task_id, session_id=session_id, intent=intent, limit=limit)
    unresolved = workspace_unresolved_items(workspace_file, task_id=focus_task_id, session_id=session_id, intent=intent, limit=limit)
    receipts = workspace_write_receipts(workspace_file, task_id=focus_task_id, session_id=session_id, limit=limit)
    handoffs = workspace_handoff_history(workspace_file, task_id=focus_task_id, session_id=session_id, limit=limit)
    evidence = workspace_recent_evidence(workspace_file, task_id=focus_task_id, session_id=session_id, limit=limit, budget=budget)
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
    if _is_compact_view(view):
        compact = _compact_continuity_dashboard(result, budget=budget)
        gain = _measure_compact_gain(result, compact)
        log_token_gain(workspace_file, "workspace_continuity_dashboard", budget=budget, model="", raw_tokens=gain["raw_tokens"], compact_tokens=gain["compact_tokens"], view=view)
        return compact
    return result


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


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


def _build_memory_layers(config, store: WorkspaceStore, active_tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
    refs_count = sum(1 for _ in store.refs_dir.rglob("*") if _.is_file()) if store.refs_dir.exists() else 0
    case_rows = store.read_jsonl_prefer_backend("cross-service-task-memory.jsonl", limit=5000)
    current_truth_cases = sum(1 for item in case_rows if item.get("current_truth", True))
    superseded_cases = sum(1 for item in case_rows if item.get("superseded_by"))
    instruction_targets = [
        config.root_path / "AGENTS.md",
        config.root_path / "CLAUDE.md",
        config.root_path / "GEMINI.md",
        config.root_path / ".github" / "copilot-instructions.md",
        config.root_path / ".cursor" / "rules" / "memory-center.mdc",
    ]
    instruction_count = sum(1 for path in instruction_targets if path.exists())
    return {
        LAYER_L0: {
            "description": "原始会话事件与外置 payload 引用",
            "event_count": len(store.read_jsonl_prefer_backend(SESSION_EVENTS_FILE, limit=5000)),
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
            "instruction_files": instruction_count,
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
    rows = store.read_jsonl_prefer_backend(WRITE_RECEIPTS_FILE, limit=5000)
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
        '  T["Task Intent"] --> S["mc_lookup (mode=code)"]',
        '  S --> Y["mc_lookup (mode=symbol)"]',
        '  Y --> C["mc_lookup (mode=chain)"]',
    ]
    if risk_level == "high":
        flow_lines.extend(
            [
                '  C --> I["mc_analyze (depth=standard)"]',
                '  I --> P["mc_analyze (depth=full)"]',
                '  P --> V["mc_analyze (checklist)"]',
            ]
        )
    elif risk_level == "medium":
        flow_lines.extend(
            [
                '  C --> P["mc_analyze (depth=standard)"]',
                '  P --> V["mc_analyze (checklist)"]',
            ]
        )
    else:
        flow_lines.append('  C --> V["mc_analyze (quick)"]')
    if has_contract:
        flow_lines.append(f'  {"P" if risk_level != "low" else "V"} --> K["mc_analyze (contract, depth=full)"]')
        flow_lines.append('  K --> R["mc_analyze (rules)"]')
    if has_mq:
        flow_lines.append(f'  {"P" if risk_level != "low" else "V"} --> M["MQ compatibility review"]')
        flow_lines.append('  M --> R["mc_analyze (rules)"]')
    if has_config:
        flow_lines.append(f'  {"P" if risk_level != "low" else "V"} --> G["Config diff review"]')
        flow_lines.append('  G --> R["mc_analyze (rules)"]')
    if not (has_contract or has_mq or has_config):
        flow_lines.append(f'  {"P" if risk_level != "low" else "V"} --> R["mc_analyze (rules)"]')
    if has_cases:
        flow_lines.append('  R --> H["Review historical cases"]')
        flow_lines.append('  H --> E["Edit & Test"]')
    else:
        flow_lines.append('  R --> E["Edit & Test"]')
    flow_lines.extend(
        [
            '  E --> S2["mc_close (end session)"]',
            '  S2 --> Y2["mc_close (sync case)"]',
            '  Y2 --> W["mc_close (record case)"]',
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


def _build_sniff_candidate_paths(
    *,
    intent: str,
    risk_level: str,
    lookup_hint: Dict[str, Any],
    task_resolution: Dict[str, Any],
    auto_sync: Dict[str, Any],
    write_judge_decision: Dict[str, Any],
    matched_files: List[Dict[str, Any]],
    related_apis: List[Dict[str, Any]],
    related_feigns: List[Dict[str, Any]],
    related_mq: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    recommended_key = str(lookup_hint.get("recommended_path", "") or "local_search")
    preferred_tools = list(lookup_hint.get("preferred_tools", []) or [])
    reasons = list(lookup_hint.get("reasons", []) or [])
    base_weight = {
        "call_chain": 0.92,
        "cross_service_analysis": 0.9,
        "symbol_lookup": 0.88,
        "keyword_lookup": 0.8,
        "local_search": 0.7,
    }.get(recommended_key, 0.72)
    candidates.append(
        {
            "candidate_type": "lookup_path",
            "target": recommended_key,
            "status": "probable",
            "weight": round(base_weight, 2),
            "why": reasons[0] if reasons else "这是当前最可能快速缩小范围的入口。",
            "next_action": _lookup_next_action(recommended_key),
            "verification_cost": "low",
            "preferred_tools": preferred_tools[:3],
            "_learning_aliases": [
                {"candidate_type": "lookup_path", "target": recommended_key},
            ],
        }
    )

    if risk_level in {"medium", "high"}:
        related_signals = sum(bool(items) for items in [related_apis, related_feigns, related_mq])
        candidates.append(
            {
                "candidate_type": "impact_analysis",
                "target": intent,
                "status": "probable" if risk_level == "medium" else "confirmed",
                "weight": 0.86 if risk_level == "medium" else 0.94,
                "why": f"当前风险等级为 {risk_level}，且已发现 {related_signals} 类跨边界信号，先做影响分析更稳。",
                "next_action": 'mc_analyze(target="...", depth="standard/full")',
                "verification_cost": "medium",
                "preferred_tools": ["mc_analyze", "workspace_trace_tool"],
                "_learning_aliases": [
                    {"candidate_type": "impact_analysis", "target": intent},
                ],
            }
        )

    if task_resolution.get("resolved"):
        candidates.append(
            {
                "candidate_type": "resume_task",
                "target": task_resolution.get("task_id", ""),
                "status": "confirmed",
                "weight": round(max(0.6, float(task_resolution.get("score", 0.0) or 0.0)), 2),
                "why": f"当前 intent 与现有任务 `{task_resolution.get('title', '')}` 已形成稳定匹配。",
                "next_action": f'mc_resume(task_id="{task_resolution.get("task_id", "")}")',
                "verification_cost": "low",
                "preferred_tools": ["mc_resume", "mc_sync"],
            }
        )

    if auto_sync.get("recommended"):
        candidates.append(
            {
                "candidate_type": "task_sync",
                "target": task_resolution.get("task_id", "") or "new-task-space",
                "status": "possible",
                "weight": 0.74,
                "why": str(auto_sync.get("reason", "") or "当前上下文适合沉淀到任务空间，避免后续重复理解。"),
                "next_action": 'mc_sync(intent="...", auto_sync_mode="balanced")',
                "verification_cost": "low",
                "preferred_tools": ["mc_sync"],
                "_learning_aliases": [
                    {"candidate_type": "task_sync", "target": task_resolution.get("task_id", "") or "new-task-space"},
                ],
            }
        )

    selected_layer = str(write_judge_decision.get("selected_layer", "") or "")
    if selected_layer:
        candidates.append(
            {
                "candidate_type": "memory_write",
                "target": selected_layer,
                "status": "possible",
                "weight": 0.68,
                "why": f"当前 intent 更适合沉淀到 {selected_layer}，便于后续复用同类决策。",
                "next_action": 'mc_admin(action="write_plan")',
                "verification_cost": "low",
                "preferred_tools": ["mc_admin", "mc_sync"],
            }
        )

    if matched_files:
        candidates.append(
            {
                "candidate_type": "live_file_check",
                "target": matched_files[0].get("path", ""),
                "status": "possible",
                "weight": 0.64,
                "why": "已有候选文件，必要时可直接读取实时文件验证，不必先展开更多链路。",
                "next_action": f'优先读取 `{matched_files[0].get("path", "")}` 实时内容',
                "verification_cost": "low",
                "preferred_tools": ["memory_search_code_tool", "local_search"],
            }
        )

    return sorted(
        candidates,
        key=lambda item: (
            0 if item.get("status") == "confirmed" else 1 if item.get("status") == "probable" else 2,
            -float(item.get("weight", 0.0)),
            item.get("candidate_type", ""),
        ),
    )


def _lookup_next_action(recommended_path: str) -> str:
    actions = {
        "symbol_lookup": 'mc_lookup(query="...", mode="symbol")',
        "call_chain": 'mc_lookup(query="...", mode="chain", chain_direction="callers/callees")',
        "cross_service_analysis": 'mc_analyze(target="...", depth="standard/full")',
        "keyword_lookup": 'mc_lookup(query="...", mode="code")',
        "local_search": "先用 rg / 本地搜索缩小范围，再回到 Memory Center 做结构化分析",
    }
    return actions.get(recommended_path, actions["local_search"])


def _build_lookup_hint_candidate_paths(
    *,
    recommended_path: str,
    preferred_tools: List[str],
    reasons: List[str],
    sniff: Dict[str, Any],
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = [
        {
            "candidate_type": "lookup_path",
            "target": recommended_path or "local_search",
            "status": "probable",
            "weight": {
                "call_chain": 0.92,
                "cross_service_analysis": 0.9,
                "symbol_lookup": 0.88,
                "keyword_lookup": 0.8,
                "local_search": 0.7,
            }.get(recommended_path or "local_search", 0.72),
            "why": reasons[0] if reasons else "这是当前 lookup 阶段最合适的入口。",
            "next_action": _lookup_next_action(recommended_path or "local_search"),
            "verification_cost": "low",
            "preferred_tools": preferred_tools[:3],
            "_learning_aliases": [
                {"candidate_type": "lookup_path", "target": recommended_path or "local_search"},
            ],
        }
    ]
    if sniff.get("risk_level") in {"medium", "high"}:
        candidates.append(
            {
                "candidate_type": "risk_validation",
                "target": sniff.get("risk_level", ""),
                "status": "possible",
                "weight": 0.78 if sniff.get("risk_level") == "medium" else 0.88,
                "why": f"当前 sniff 风险等级为 {sniff.get('risk_level', '')}，建议尽早转入结构化验证。",
                "next_action": 'mc_analyze(target="...", depth="standard/full")',
                "verification_cost": "medium",
                "preferred_tools": ["mc_analyze"],
            }
        )
    if sniff.get("candidate_files"):
        candidates.append(
            {
                "candidate_type": "live_file_check",
                "target": (sniff.get("candidate_files", [{}])[0] or {}).get("path", ""),
                "status": "possible",
                "weight": 0.64,
                "why": "已有候选文件，可直接读取 live file 做低成本确认。",
                "next_action": f'优先读取 `{(sniff.get("candidate_files", [{}])[0] or {}).get("path", "")}` 实时内容',
                "verification_cost": "low",
                "preferred_tools": ["memory_search_code_tool", "local_search"],
            }
        )
    return candidates


def workspace_check_contract(workspace_file: str | Path, contract_file: str, change_type: str) -> Dict[str, Any]:
    _, store = load_context(workspace_file)
    files = store.read_json_prefer_backend("file-index.json", [])
    feigns = store.read_json_prefer_backend("feign-index.json", [])
    mq = store.read_json_prefer_backend("mq-index.json", [])
    basename = Path(contract_file).stem.lower()
    affected = []
    for item in files:
        text = item.get("path", "").lower()
        if basename in text:
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
