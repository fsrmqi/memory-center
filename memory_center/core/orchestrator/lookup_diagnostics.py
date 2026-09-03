"""Reference and backend diagnostic lookup APIs separated from query facade."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from .lookup_shared import DiagnosticsLookupPort

def get_ref(workspace_file: str | Path, ref_id: str, *, deps: DiagnosticsLookupPort) -> dict[str, Any]:
    config, store = deps.load_context(workspace_file); resolved = deps.resolve_ref(store, ref_id)
    if not resolved:
        return deps.with_schema("memory_ref", {"workspace": config.workspace, "ref_id": ref_id, "kind": "unknown", "summary": "", "raw": None, "timeline_ref": None, "found": False})
    raw = resolved.get("raw"); timeline = None
    if isinstance(raw, dict):
        sid = raw.get("session_id") or (raw.get("event", {}) or {}).get("session_id", ""); tid = raw.get("task_id") or (raw.get("event", {}) or {}).get("task_id", "")
        if sid or tid: timeline = "/ui/timeline?" + "&".join(([f"task_id={tid}"] if tid else []) + ([f"session_id={sid}"] if sid else []))
    return deps.with_schema("memory_ref", {"workspace": config.workspace, "ref_id": ref_id, "kind": resolved.get("kind", "unknown"), "summary": resolved.get("summary", ""), "raw": raw, "timeline_ref": timeline, "found": True})

def get_ref_batch(workspace_file: str | Path, ref_ids: list[str], *, deps: DiagnosticsLookupPort) -> dict[str, Any]:
    from memory_center.core.workspace.config import load_workspace_config
    refs = [get_ref(workspace_file, ref, deps=deps) for ref in ref_ids]
    return deps.with_schema("memory_ref_batch", {"workspace": load_workspace_config(workspace_file).workspace, "requested": ref_ids, "found_count": sum(item.get("found") for item in refs), "refs": refs})

def backend_query(workspace_file: str | Path, *, deps: DiagnosticsLookupPort, **filters: Any) -> dict[str, Any]:
    config, store = deps.load_context(workspace_file); limit = int(filters.get("limit", 50))
    return {"workspace": config.workspace, "records": store.memory_backend_query_records(collection=filters.get("collection", ""), record_id=filters.get("record_id", ""), created_after=filters.get("created_after", ""), project=filters.get("project", ""), payload_type=filters.get("payload_type", ""), limit=limit), "refs": store.memory_backend_query_refs(ref_path=filters.get("ref_path", ""), limit=limit)}

def tool_usage_report(workspace_file: str | Path, limit: int = 200, *, deps: DiagnosticsLookupPort) -> dict[str, Any]:
    import json
    from .shared import SESSION_EVENTS_FILE
    config, store = deps.load_context(workspace_file); events = store.read_jsonl_prefer_backend(SESSION_EVENTS_FILE, limit=max(limit, 1))
    counts: dict[str, int] = {}; lookup: dict[str, int] = {}; mc = external = 0; bypass = []
    lookup_tools = {"memory_symbol_tool", "memory_search_code_tool", "workspace_trace_tool", "memory_callers_tool", "memory_callees_tool", "memory_context_tool", "memory_impact_tool", "workspace_sniff_tool"}
    for event in events:
        if event.get("event_type") != "tool_call": continue
        payload = deps.event_payload(event); name = str(payload.get("tool_name") or payload.get("name") or "")
        if not name: continue
        counts[name] = counts.get(name, 0) + 1; is_mc = name.startswith("memory_") or name.startswith("workspace_"); mc += int(is_mc); external += int(not is_mc)
        if name in lookup_tools: lookup[name] = lookup.get(name, 0) + 1
        if not is_mc and any(token in json.dumps(payload, ensure_ascii=False).lower() for token in ("class", "method", "feign", "topic", "caller", "callee", "symbol", "controller", "service", "类", "方法", "调用链")):
            bypass.append({"session_id": event.get("session_id", ""), "tool_name": name, "query": payload.get("query", "") or payload.get("target", "") or payload.get("text", ""), "reason": "看起来是在做类/符号/调用链检索，但没有走 Memory Center 工具。"})
    total = mc + external; summary = {"total_tool_calls": total, "memory_center_calls": mc, "external_calls": external, "memory_center_ratio": round(mc / total, 3) if total else 0.0, "lookup_tool_total": sum(lookup.values()), "suspected_bypass_count": len(bypass)}
    hints = []
    if not sum(lookup.values()): hints.append("最近会话里几乎没有使用 Memory Center 的 lookup 工具，找类/符号很可能仍主要依赖本地搜索。")
    if bypass: hints.append("检测到疑似绕过案例，建议继续把类/符号/调用链检索优先协议前置到生成指令里。")
    if summary["memory_center_ratio"] < .4 and total: hints.append("Memory Center 工具调用占比较低，可能意味着协议优先级还不够高，或返回结果还不够有吸引力。")
    if not hints: hints.append("近期使用情况正常，Memory Center 已经开始承担主要检索与连续性职责。")
    return deps.with_schema("tool_usage_report", {"workspace": config.workspace, "summary": summary, "tool_counts": dict(sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:20]), "lookup_tool_counts": dict(sorted(lookup.items(), key=lambda item: (-item[1], item[0]))), "suspected_bypass": bypass[:20], "adoption_hints": hints})

def discover(workspace_file: str | Path, limit: int = 50, *, deps: DiagnosticsLookupPort) -> dict[str, Any]:
    from .shared import SESSION_EVENTS_FILE
    config, store = deps.load_context(workspace_file); events = store.read_jsonl_prefer_backend(SESSION_EVENTS_FILE, limit=max(limit, 200)); counts = {}; queries = []
    for event in events:
        if event.get("event_type") != "tool_call": continue
        payload = deps.event_payload(event); name = str(payload.get("tool_name") or payload.get("name") or "")
        if name: counts[name] = counts.get(name, 0) + 1
        if text := payload.get("query", "") or payload.get("target", "") or payload.get("text", ""): queries.append(text)
    paths = [{"candidate_type": "runtime_governance", "target": "continue-current-workflow", "status": "possible", "weight": .62, "why": "当前工作区状态整体正常，可继续沿现有工作流推进。", "next_action": "继续当前任务；必要时用 `mc_lookup` / `mc_analyze` 深挖", "verification_cost": "low"}]
    try:
        from .workspace_ops import workspace_status
        from ..verification.heuristics import apply_candidate_path_learning
        layers = workspace_status(workspace_file, view="compact", budget="medium").get("memory_layers", {})
        if layers.get("L0", {}).get("count", 0) == 0: paths.insert(0, {"candidate_type": "session_bootstrap", "target": "work-start", "status": "probable", "weight": .76, "why": "当前还没有会话事件，先启动工作流能尽快建立上下文轨迹。", "next_action": "先运行 `work-start` 或 `mc_start` 启动任务", "verification_cost": "low"})
        if layers.get("L1", {}).get("count", 0) == 0: paths.append({"candidate_type": "memory_write", "target": "L1_case_atom", "status": "possible", "weight": .7, "why": "当前缺少案例记忆，补齐 case 沉淀可以提升后续复用价值。", "next_action": "在关键阶段后运行 `work-sync` 或 `mc_sync`", "verification_cost": "low"})
        if layers.get("L2", {}).get("count", 0) == 0: paths.append({"candidate_type": "task_sync", "target": "new-task-space", "status": "probable", "weight": .78, "why": "当前缺少任务空间，先创建 task 能让长任务协作更稳定。", "next_action": "运行 `artifact create-task` 或 `mc_sync(intent=...)`", "verification_cost": "low", "_learning_aliases": [{"candidate_type": "task_sync", "target": "new-task-space"}]})
        paths = apply_candidate_path_learning(workspace_file, paths)
    except Exception: pass
    matrix = {"quick_context": {"command": "mc_lookup", "mode": "auto", "view": "compact", "budget": "small"}, "full_chain": {"command": "mc_lookup", "mode": "chain", "scope": "cross-service"}, "impact_check": {"command": "mc_analyze", "depth": "quick"}, "resume_work": {"command": "mc_resume"}, "handoff_model": {"command": "mc_handoff"}}
    return {"workspace": config.workspace, "hot_commands": [{"tool": name, "count": count} for name, count in sorted(counts.items(), key=lambda item: -item[1])[:10]], "recent_queries": queries[:10], "recommendations": [path["why"] for path in paths], "candidate_paths": paths, "recommended_path": dict(paths[0]), "compression_matrix": matrix}
