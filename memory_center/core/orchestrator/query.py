from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from ..graph import GraphStore
from ..rules import match_rules
from ..schemas import with_schema
from ..semantic import semantic_index_stats, semantic_query
from .common import (
    SESSION_EVENTS_FILE,
    _best_match,
    _build_progressive_levels,
    _event_payload,
    _filter_call_edges,
    _node_type_priority,
    _render_ref_label,
    _resolve_memory_ref,
    _rrf,
    load_context,
    preferred_edge_types,
    tokenize,
)


def memory_query(workspace_file: str | Path, query: str, limit: int = 20, node_types: List[str] | None = None, alpha: float | None = None) -> Dict[str, Any]:
    config, store = load_context(workspace_file)
    with GraphStore(store.graph_db_path) as graph:
        exact_nodes = graph.find_nodes(query, types=node_types, limit=limit)
        if not exact_nodes:
            seen_nodes = {}
            for token in tokenize(query):
                for item in graph.find_nodes(token, types=node_types, limit=limit):
                    seen_nodes[item["id"]] = item
            exact_nodes = list(seen_nodes.values())[:limit]
    semantic_hits = semantic_query(workspace_file, query, limit=max(limit * 3, 20))
    # 复用同一个 GraphStore 连接来 enrich 所有 semantic hits，避免每个 hit 单独打开连接
    enriched_semantic_hits = []
    with GraphStore(store.graph_db_path) as graph:
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
    with GraphStore(store.graph_db_path) as graph:
        merged = _merge_workspace_query_hits(graph, query, exact_nodes, semantic_hits, limit, alpha=alpha)
    related_rules = match_rules(store, intent=query, files=[item["node"].get("file_path", "") for item in merged])[:10]
    cases = store.read_jsonl_prefer_backend("cross-service-task-memory.jsonl", limit=200)
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


def memory_query_hybrid(workspace_file: str | Path, query: str, limit: int = 20, node_types: List[str] | None = None, config: Any = None) -> Dict[str, Any]:
    """Enhanced query using hybrid retrieval engine.

    Combines graph, sparse, and semantic search with intelligent routing.
    Provides better recall and more stable results than memory_query.
    """
    # Lazy import to avoid circular dependency
    from ..retrieval.hybrid import HybridRetrievalConfig, hybrid_retrieve, detect_query_intent

    config_obj = load_context(workspace_file)
    store = config_obj[1]

    # Convert config if needed
    if config is None:
        config = HybridRetrievalConfig()

    # Detect query intent first
    intent = detect_query_intent(query)

    with GraphStore(store.graph_db_path) as graph:
        result = hybrid_retrieve(
            graph=graph,
            workspace_file=str(workspace_file),
            query=query,
            config=config,
            node_types=node_types,
            limit=limit,
        )

    # Enrich with workspace context
    result["workspace"] = config_obj[0].workspace
    result["intent_analysis"] = intent

    # 根据意图补充 contracts 索引数据
    primary_intent = intent.get("primary_intent", "general")
    if primary_intent in ("feign", "mq", "endpoint", "config"):
        contracts = memory_contracts(workspace_file)
        filtered_feign = _filter_contracts_by_query(contracts.get("feign_contracts", []), query, primary_intent)
        filtered_mq = _filter_contracts_by_query(contracts.get("mq_contracts", []), query, primary_intent)
        filtered_api = _filter_contracts_by_query(contracts.get("api_contracts", []), query, primary_intent)

        # Feign 去重（worktree 可能产生重复）
        if filtered_feign:
            seen_interfaces = set()
            deduped_feign = []
            for fc in filtered_feign:
                key = (fc.get("interface", ""), fc.get("project", ""))
                if key not in seen_interfaces:
                    seen_interfaces.add(key)
                    deduped_feign.append(fc)
            filtered_feign = deduped_feign

        # Feign → API 自动关联：只关联查询直接匹配的方法
        linked_api = []
        if primary_intent == "feign" and filtered_feign:
            api_by_path = {c.get("path", ""): c for c in contracts.get("api_contracts", [])}
            query_lower_local = query.lower()
            for fc in filtered_feign:
                for m in fc.get("methods", []):
                    method_name = m.get("method_name", "").lower()
                    m_path = m.get("path", "")
                    # 只关联查询直接匹配的方法
                    if query_lower_local in method_name or method_name in query_lower_local:
                        if m_path and m_path in api_by_path:
                            matched_api = api_by_path[m_path]
                            if matched_api not in linked_api:
                                linked_api.append(matched_api)
            # feign 意图：只返回关联的 API
            filtered_api = linked_api

        result["contracts"] = {
            "feign_contracts": filtered_feign,
            "mq_contracts": filtered_mq,
            "api_contracts": filtered_api,
        }
        # 标记 contracts 数据来源
        if "retrieval_sources" not in result:
            result["retrieval_sources"] = []
        result["retrieval_sources"].append("contracts_index")

    # 向后兼容：添加 matches 字段（旧接口返回 matches，新接口返回 results）
    if "results" in result and "matches" not in result:
        result["matches"] = result["results"]

    # 确保 retrieval_summary 包含旧接口期望的字段
    if "retrieval_summary" in result:
        summary = result["retrieval_summary"]
        if "exact_matches" not in summary:
            summary["exact_matches"] = summary.get("source_distribution", {}).get("graph", 0)
        if "semantic_matches" not in summary:
            summary["semantic_matches"] = summary.get("source_distribution", {}).get("semantic", 0)

    return result


def _filter_contracts_by_query(contracts: list, query: str, intent: str) -> list:
    """Filter contracts by query relevance."""
    if not contracts:
        return []

    query_lower = query.lower()
    tokens = tokenize(query_lower)
    exact_matches = []
    partial_matches = []

    for contract in contracts:
        contract_str = json.dumps(contract, ensure_ascii=False).lower()

        # 精确匹配：接口名或方法名完全包含查询
        if intent == "feign" and "interface" in contract:
            interface_name = contract.get("interface", "").lower()
            # 接口名完全匹配或包含查询
            if query_lower in interface_name or interface_name in query_lower:
                exact_matches.append(contract)
                continue
            # 方法名精确匹配
            for m in contract.get("methods", []):
                if query_lower in m.get("method_name", "").lower():
                    exact_matches.append(contract)
                    break
            else:
                # Token 匹配
                if any(token in interface_name for token in tokens):
                    partial_matches.append(contract)
        elif intent == "endpoint" and "path" in contract:
            path = contract.get("path", "").lower()
            controller = contract.get("controller", "").lower()
            if query_lower in path or query_lower in controller:
                exact_matches.append(contract)
            elif any(token in path or token in controller for token in tokens):
                partial_matches.append(contract)
        else:
            # 通用匹配
            if any(token in contract_str for token in tokens):
                partial_matches.append(contract)

    # 精确匹配优先，然后是部分匹配
    result = exact_matches + partial_matches
    return result[:20] if result else contracts[:10]


def memory_context(workspace_file: str | Path, name: str, max_depth: int = 2) -> Dict[str, Any]:
    lookup = memory_query(workspace_file, name, limit=8)
    matches = [item.get("node", {}) for item in lookup.get("matches", []) if item.get("node")]
    if not matches:
        return {"name": name, "found": False, "matches": [], "lookup": _build_lookup_payload(lookup)}
    node = _best_match(matches, name)
    with GraphStore(load_context(workspace_file)[1].graph_db_path) as graph:
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


def memory_callers(workspace_file: str | Path, symbol: str, depth: int = 2, limit: int = 80, edge_type_filter: List[str] | None = None) -> Dict[str, Any]:
    info = memory_symbol(workspace_file, symbol, limit=8)
    if not info.get("found"):
        return {"symbol": symbol, "found": False, "callers": [], "lookup": info.get("lookup", {})}
    node = info["best_match"]
    et = edge_type_filter or preferred_edge_types("upstream")
    with GraphStore(load_context(workspace_file)[1].graph_db_path) as graph:
        edges = graph.neighbors(node["id"], direction="upstream", max_depth=depth, limit=limit, edge_types=et)
    callers = _filter_call_edges(edges, direction="upstream")[:limit]
    return {
        "symbol": symbol,
        "found": True,
        "target": node,
        "depth": depth,
        "callers": callers,
        "chain_tree": _compress_chain_tree(callers),
        "lookup": info.get("lookup", {}),
    }


def memory_callees(workspace_file: str | Path, symbol: str, depth: int = 2, limit: int = 80, edge_type_filter: List[str] | None = None) -> Dict[str, Any]:
    info = memory_symbol(workspace_file, symbol, limit=8)
    if not info.get("found"):
        return {"symbol": symbol, "found": False, "callees": [], "lookup": info.get("lookup", {})}
    node = info["best_match"]
    et = edge_type_filter or preferred_edge_types("downstream")
    with GraphStore(load_context(workspace_file)[1].graph_db_path) as graph:
        edges = graph.neighbors(node["id"], direction="downstream", max_depth=depth, limit=limit, edge_types=et)
    callees = _filter_call_edges(edges, direction="downstream")[:limit]
    return {
        "symbol": symbol,
        "found": True,
        "target": node,
        "depth": depth,
        "callees": callees,
        "chain_tree": _compress_chain_tree(callees),
        "lookup": info.get("lookup", {}),
    }


def memory_search_code(workspace_file: str | Path, query: str, scope: str = "", limit: int = 20) -> Dict[str, Any]:
    config, store = load_context(workspace_file)
    keywords = tokenize(query)
    files = store.read_json_prefer_backend("file-index.json", [])
    symbols = store.read_json_prefer_backend("java-symbol-index.json", [])
    symbol_entries = {}
    for item in symbols:
        key = item.get("file", "")
        symbol_entries.setdefault(key, []).append(item)
    scope_l = scope.lower().strip()
    hits: List[Dict[str, Any]] = []
    for item in files:
        path = item.get("path", "")
        if scope_l and scope_l not in path.lower():
            continue
        text = f"{path} {item.get('project', '')} {item.get('service_name', '')}".lower()
        file_symbols = symbol_entries.get(path, [])
        symbol_text = json.dumps(file_symbols, ensure_ascii=False).lower()
        score = sum(1 for token in keywords if token in text or token in symbol_text)
        if score <= 0:
            continue
        hits.append(
            {
                "project": item.get("project", ""),
                "service_name": item.get("service_name", ""),
                "path": path,
                "score": score,
                "symbol_count": sum(
                    int(sym.get("class_count", 0)) + int(sym.get("method_count", 0)) + int(sym.get("field_count", 0))
                    for sym in file_symbols
                ),
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


def memory_contracts(workspace_file: str | Path) -> Dict[str, Any]:
    _, store = load_context(workspace_file)
    return {
        "feign_contracts": store.read_json_prefer_backend("feign-index.json", []),
        "mq_contracts": store.read_json_prefer_backend("mq-index.json", []),
        "api_contracts": store.read_json_prefer_backend("api-index.json", []),
        "rules": match_rules(store, intent="contract feign dto message api", scopes=["contract", "dto", "feign", "message"]),
    }


def memory_ref_get(workspace_file: str | Path, ref_id: str) -> Dict[str, Any]:
    config, store = load_context(workspace_file)
    resolved = _resolve_memory_ref(store, ref_id)
    if not resolved:
        return with_schema(
            "memory_ref",
            {
                "workspace": config.workspace,
                "ref_id": ref_id,
                "kind": "unknown",
                "summary": "",
                "raw": None,
                "timeline_ref": None,
                "found": False,
            },
        )
    raw = resolved.get("raw")
    # Build reverse timeline link from session_id/task_id in raw data
    timeline_ref = None
    if isinstance(raw, dict):
        sid = raw.get("session_id") or (raw.get("event", {}) or {}).get("session_id", "")
        tid = raw.get("task_id") or (raw.get("event", {}) or {}).get("task_id", "")
        if sid or tid:
            params = []
            if tid:
                params.append(f"task_id={tid}")
            if sid:
                params.append(f"session_id={sid}")
            timeline_ref = "/ui/timeline?" + "&".join(params)
    return with_schema(
        "memory_ref",
        {
            "workspace": config.workspace,
            "ref_id": ref_id,
            "kind": resolved.get("kind", "unknown"),
            "summary": resolved.get("summary", ""),
            "raw": resolved.get("raw"),
            "timeline_ref": timeline_ref,
            "found": True,
        },
    )


def memory_ref_batch(workspace_file: str | Path, ref_ids: List[str]) -> Dict[str, Any]:
    from ..config import load_workspace_config

    refs = [memory_ref_get(workspace_file, ref_id) for ref_id in ref_ids]
    return with_schema(
        "memory_ref_batch",
        {
            "workspace": load_workspace_config(workspace_file).workspace,
            "requested": ref_ids,
            "found_count": sum(1 for item in refs if item.get("found")),
            "refs": refs,
        },
    )


def memory_backend_query(
    workspace_file: str | Path,
    *,
    collection: str = "",
    record_id: str = "",
    created_after: str = "",
    ref_path: str = "",
    project: str = "",
    payload_type: str = "",
    limit: int = 50,
) -> Dict[str, Any]:
    config, store = load_context(workspace_file)
    return {
        "workspace": config.workspace,
        "records": store.memory_backend_query_records(collection=collection, record_id=record_id, created_after=created_after, project=project, payload_type=payload_type, limit=limit),
        "refs": store.memory_backend_query_refs(ref_path=ref_path, limit=limit),
    }


def memory_tool_usage_report(
    workspace_file: str | Path,
    limit: int = 200,
) -> Dict[str, Any]:
    config, store = load_context(workspace_file)
    events = store.read_jsonl_prefer_backend(SESSION_EVENTS_FILE, limit=max(limit, 1))
    tool_counts: Dict[str, int] = {}
    lookup_tool_counts: Dict[str, int] = {}
    memory_center_calls = 0
    external_calls = 0
    suspected_bypass: List[Dict[str, Any]] = []
    lookup_tools = {
        "memory_symbol_tool", "memory_search_code_tool", "workspace_trace_tool",
        "memory_callers_tool", "memory_callees_tool", "memory_context_tool",
        "memory_impact_tool", "workspace_sniff_tool",
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


# ---- internal helpers -------------------------------------------------------

def _compress_chain_tree(edges: List[Dict[str, Any]]) -> Dict[str, Any]:
    tree: Dict[str, List[Dict[str, Any]]] = {}
    for e in edges:
        src = e.get("source", {}).get("name", "?")
        tgt = e.get("target", {}).get("name", "?")
        tgt_proj = e.get("target", {}).get("project", "")
        edge_type = e.get("type", "")
        depth = e.get("depth", 0)
        tree.setdefault(src, []).append({
            "target": tgt, "type": edge_type,
            "project": tgt_proj, "depth": depth,
        })
    return {
        "tree": tree,
        "depth_reached": max((e.get("depth", 0) for e in edges), default=0),
        "total_edges": len(edges),
        "unique_sources": len(tree),
    }


def _annotate_phantom_nodes(chain_result: Dict[str, Any], workspace_file: str | Path) -> None:
    config, store = load_context(workspace_file)
    topology = store.read_json_prefer_backend("service-topology.json", {})
    local_services = {svc.get("service_name") or svc.get("name") for svc in topology.get("services", [])}
    edges_key = "callers" if "callers" in chain_result else "callees"
    for edge in chain_result.get(edges_key, []):
        if edge.get("type") != "CALLS_SERVICE":
            continue
        target = edge.get("target", {})
        if target.get("type") == "Service" and target.get("name", "") not in local_services:
            hint = edge.get("metadata", {}).get("target_service") or target.get("name", "")
            target["_is_external_service"] = True
            target["_external_service_hint"] = hint
            edge["_is_external_service"] = True
            edge["_external_service_hint"] = hint
            edge["_boundary_type"] = "feign-service-phantom"


def _merge_workspace_query_hits(
    graph: GraphStore,
    query: str,
    exact_nodes: List[Dict[str, Any]],
    semantic_hits: List[Dict[str, Any]],
    limit: int,
    alpha: float | None = None,
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
    resolved_target_types = _resolve_query_target_types(query, sorted(t for t in target_types if t))
    matches = list(merged.values())
    matches.sort(key=lambda item: _workspace_query_match_key(item, resolved_target_types, alpha=alpha))
    return matches[:limit]


def _workspace_query_match_key(item: Dict[str, Any], target_types: List[str], alpha: float | None = None) -> tuple:
    node = item.get("node", {})
    priority = _query_node_priority(node.get("type", ""), target_types)
    sources = set(item.get("retrieval_sources", []))
    hybrid_rank = 0 if {"exact", "semantic"} <= sources else 1 if "exact" in sources else 2 if "semantic" in sources else 3
    exact_score = float(item.get("exact_score", 0.0))
    semantic_score = float(item.get("semantic_score", 0.0))
    if alpha is not None:
        # Blended scoring: alpha * exact + (1-alpha) * semantic + dual_bonus
        dual_bonus = 0.1 if {"exact", "semantic"} <= sources else 0.0
        blended = alpha * exact_score + (1 - alpha) * semantic_score + dual_bonus
        return (priority, -blended, -exact_score, -semantic_score, int(item.get("best_rank", 9999)), node.get("name", ""))
    return (
        priority,
        hybrid_rank,
        -exact_score,
        -semantic_score,
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


def _resolve_query_target_types(target: str, target_types: List[str]) -> List[str]:
    resolved = set(t for t in target_types if t)
    target_lower = target.lower()
    service_indicators = {"service", "api", "common", "gateway", "server", "app", "web", "ui", "frontend", "backend", "admin", "portal"}
    hyphen_like = "-" in target_lower and not any(ind in target_lower for ind in service_indicators)
    topic_like = hyphen_like or any(token in target_lower for token in ["topic", "kafka", "rocketmq", "consumer", "producer", "listener"])
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
        "FeignClient": 0, "FeignMethod": 1, "Endpoint": 2, "MQTopic": 3, "MQConsumer": 4,
        "ConfigKey": 5, "Field": 6, "Method": 7, "Class": 8, "File": 20,
    }
    return sorted({item for item in target_types if item}, key=lambda item: (priority.get(item, 10), item))


def _summarize_query_matches(matches: List[Dict[str, Any]], limit: int) -> Dict[str, int]:
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


def _build_search_progressive_view(query: str, scope: str, hits: List[Dict[str, Any]]) -> Dict[str, Any]:
    return _build_progressive_levels(
        {"query": query, "scope": scope, "top_hit_count": len(hits), "top_paths": [item.get("path", "") for item in hits[:3]]},
        {
            "top_projects": sorted({item.get("project", "") for item in hits[:5] if item.get("project")}),
            "scored_hits": [{"path": item.get("path", ""), "score": item.get("score", 0)} for item in hits[:5]],
        },
        {"next_action": "对 top_paths 调用 memory_symbol / memory_context 深挖。", "full_paths": [item.get("path", "") for item in hits]},
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
                {"node_id": item.get("node_id", ""), "name": item.get("node", {}).get("name", ""), "score": item.get("score", 0.0)}
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
