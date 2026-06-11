from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from ..graph import GraphStore
from ..rules import match_rules
from ..schemas import with_schema
from ..semantic import semantic_index_stats, semantic_query
from ..ontology import EntityValidator
from ..diagnostics import DIAG, diag_entry, safe_reason
from ..verification.heuristics import apply_candidate_path_learning
from ..tracking import log_token_gain
from .common import (
    SESSION_EVENTS_FILE,
    _best_match,
    _build_progressive_levels,
    _event_payload,
    _filter_call_edges,
    _is_compact_view,
    _node_type_priority,
    _render_ref_label,
    _resolve_memory_ref,
    _rrf,
    load_context,
    preferred_edge_types,
    tokenize,
)
from .compact import _measure_compact_gain


def _normalize_symbol_name(name: str) -> str:
    normalized = (name or "").strip().replace("#", ".")
    if not normalized:
        return ""
    return normalized.split(".")[-1]


def _looks_like_class_symbol_query(query: str) -> bool:
    token = _normalize_symbol_name(query)
    if not token or any(ch.isspace() for ch in query):
        return False
    return bool(Path(token).name == token and token[:1].isupper())


def _node_matches_symbol_query(node: Dict[str, Any], query: str) -> bool:
    target = _normalize_symbol_name(query).lower()
    if not target:
        return False
    name = str(node.get("name", "") or "").strip()
    if not name:
        return False
    short = name.split(".")[-1].lower()
    return short == target or name.lower() == target


def _has_exact_lookup_source(item: Dict[str, Any]) -> bool:
    sources = set(item.get("sources", []) or item.get("retrieval_sources", []) or [])
    return bool({"exact", "graph_exact", "graph_token", "sparse_fts", "sparse_bm25", "direct_lookup"} & sources)


def _pick_symbol_anchor(items: List[Dict[str, Any]], query: str) -> Dict[str, Any]:
    exact_classes = [
        item for item in items
        if item.get("node", item).get("type") == "Class"
        and _node_matches_symbol_query(item.get("node", item), query)
    ]
    if not exact_classes:
        return {}
    exact_classes.sort(
        key=lambda item: (
            0 if _has_exact_lookup_source(item) else 1,
            -float(item.get("score", item.get("exact_score", 0.0)) or 0.0),
            item.get("node", item).get("project", ""),
            item.get("node", item).get("file_path", ""),
        )
    )
    return exact_classes[0].get("node", exact_classes[0])


def _pick_symbol_declaration_fallback(items: List[Dict[str, Any]], query: str) -> Dict[str, Any]:
    declaration_types = {"Class", "FeignClient", "Endpoint", "MQTopic", "MQConsumer", "ConfigKey"}
    exact_declarations = [
        item for item in items
        if item.get("node", item).get("type") in declaration_types
        and _node_matches_symbol_query(item.get("node", item), query)
    ]
    if not exact_declarations:
        return {}
    exact_declarations.sort(
        key=lambda item: (
            0 if item.get("node", item).get("type") == "Class" else 1,
            0 if _has_exact_lookup_source(item) else 1,
            -float(item.get("score", item.get("exact_score", 0.0)) or 0.0),
            item.get("node", item).get("project", ""),
            item.get("node", item).get("file_path", ""),
        )
    )
    return exact_declarations[0].get("node", exact_declarations[0])


def _symbol_rank_bucket(node: Dict[str, Any], query: str, anchor: Dict[str, Any]) -> int:
    node_type = node.get("type", "")
    same_name = _node_matches_symbol_query(node, query)
    same_file = bool(anchor) and node.get("file_path", "") == anchor.get("file_path", "")
    same_project = bool(anchor) and node.get("project", "") == anchor.get("project", "")

    if node_type == "Class" and same_name:
        return 0
    if same_file and node_type == "FeignClient":
        return 1
    if same_file and node_type in {"Method", "FeignMethod", "Endpoint"}:
        return 2
    if same_file and node_type == "File":
        return 3
    if same_project and same_name and node_type in {"FeignClient", "Endpoint"}:
        return 4
    if same_project and node_type in {"Method", "FeignMethod"}:
        return 5
    if same_project and node_type == "File":
        return 6
    if node_type == "Class":
        return 7
    if node_type in {"FeignClient", "Endpoint"} and same_name:
        return 8
    if node_type in {"Method", "FeignMethod"}:
        return 9
    if node_type == "File":
        return 10
    if node_type == "Field":
        return 11
    return 20


def _rerank_symbol_like_matches(items: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
    if not _looks_like_class_symbol_query(query):
        return items
    if not any(
        (item.get("node", item).get("type") == "Class") and _node_matches_symbol_query(item.get("node", item), query)
        for item in items
    ):
        return items
    anchor = _pick_symbol_anchor(items, query)

    def key(item: Dict[str, Any]) -> tuple:
        node = item.get("node", item)
        sources = set(item.get("sources", []) or item.get("retrieval_sources", []) or [])
        semantic_only = sources == {"semantic"}
        return (
            _symbol_rank_bucket(node, query, anchor),
            0 if _node_matches_symbol_query(node, query) else 1,
            0 if anchor and node.get("file_path", "") == anchor.get("file_path", "") else 1,
            0 if anchor and node.get("project", "") == anchor.get("project", "") else 1,
            0 if _has_exact_lookup_source(item) else 1,
            1 if semantic_only else 0,
            _node_type_priority(node.get("type", "")),
            -float(item.get("score", item.get("exact_score", 0.0)) or 0.0),
            int(node.get("line", 0) or 0) == 0,
            node.get("name", ""),
        )

    return sorted(items, key=key)


def _dedupe_symbol_display_matches(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not items:
        return items

    def dedupe_key(item: Dict[str, Any]) -> tuple[str, str, str] | None:
        node = item.get("node", item)
        node_type = node.get("type", "")
        if node_type not in {"Method", "FeignMethod"}:
            return None
        return (
            str(node.get("project", "") or ""),
            str(node.get("file_path", "") or ""),
            str(node.get("name", "") or ""),
        )

    def type_priority(item: Dict[str, Any]) -> tuple[int, float]:
        node = item.get("node", item)
        node_type = node.get("type", "")
        priority = {"FeignMethod": 0, "Method": 1}
        return (
            priority.get(node_type, 10),
            -float(item.get("score", item.get("exact_score", 0.0)) or 0.0),
        )

    deduped: List[Dict[str, Any]] = []
    seen: Dict[tuple[str, str, str], int] = {}
    for item in items:
        key = dedupe_key(item)
        if key is None:
            deduped.append(item)
            continue
        existing_index = seen.get(key)
        if existing_index is None:
            seen[key] = len(deduped)
            deduped.append(item)
            continue
        if type_priority(item) < type_priority(deduped[existing_index]):
            deduped[existing_index] = item
    return deduped


def _suppress_semantic_only_noise(items: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
    strong_exact_hit = any(_has_exact_lookup_source(item) and _node_matches_symbol_query(item.get("node", item), query) for item in items)
    if not strong_exact_hit:
        return items
    adjusted: List[Dict[str, Any]] = []
    for item in items:
        copied = dict(item)
        sources = set(copied.get("sources", []) or copied.get("retrieval_sources", []) or [])
        if sources == {"semantic"}:
            copied["semantic_score"] = float(copied.get("semantic_score", copied.get("score", 0.0)) or 0.0) * 0.4
            copied["_semantic_penalty"] = "strong_exact_present"
        adjusted.append(copied)
    return adjusted


def _rebuild_summary_after_filter(filtered: list, intent: dict) -> dict:
    """Rebuild total_found / returned / retrieval_summary / progressive from filtered dicts.

    After project filtering narrows ``result["results"]``, the summary fields
    produced by ``hybrid_retrieve`` are stale (they reflect the pre-filter set).
    This rebuilds them so callers see consistent numbers.
    """
    source_counts = {"graph": 0, "sparse": 0, "semantic": 0}
    type_counts: Dict[str, int] = {}
    for item in filtered:
        for src in item.get("sources", []):
            if "graph" in src:
                source_counts["graph"] += 1
            elif "sparse" in src or "fts" in src:
                source_counts["sparse"] += 1
            elif "semantic" in src:
                source_counts["semantic"] += 1
        node_type = item.get("node", {}).get("type", "unknown")
        type_counts[node_type] = type_counts.get(node_type, 0) + 1

    retrieval_summary = {
        "total_results": len(filtered),
        "source_distribution": source_counts,
        "type_distribution": type_counts,
        "primary_intent": intent.get("primary_intent", "general"),
        "is_cross_service": intent.get("is_cross_service", False),
        "avg_score": round(sum(r.get("score", 0) for r in filtered) / max(len(filtered), 1), 4),
        "exact_matches": source_counts.get("graph", 0),
        "semantic_matches": source_counts.get("semantic", 0),
    }

    top_nodes = filtered[:3]
    primary_intent = intent.get("primary_intent", "general")
    next_actions: list = []
    if not filtered:
        next_actions.append("尝试更具体的查询词")
    elif primary_intent == "feign":
        next_actions.extend(["调用 mc_lookup(mode='context') 查看 Feign 客户端详情", "调用 mc_lookup(mode='chain') 查找调用方"])
    elif primary_intent == "mq":
        next_actions.extend(["调用 mc_lookup(mode='context') 查看 Topic/Consumer 详情"])
    elif primary_intent == "endpoint":
        next_actions.extend(["调用 mc_lookup(mode='context') 查看 API 端点详情"])
    else:
        next_actions.extend(["对 top 结果调用 mc_lookup(mode='context') 深挖", "修改代码前调用 mc_analyze 检查影响面"])

    progressive = {
        "level_1_quick": {
            "count": len(filtered),
            "top_matches": [
                {
                    "type": r.get("node", {}).get("type", ""),
                    "name": r.get("node", {}).get("name", ""),
                    "project": r.get("node", {}).get("project", ""),
                    "score": round(r.get("score", 0), 2),
                }
                for r in top_nodes
            ],
            "intent": primary_intent,
        },
        "level_2_details": {
            "sources_breakdown": {
                "graph_exact": sum(1 for r in filtered if "graph_exact" in r.get("sources", [])),
                "graph_token": sum(1 for r in filtered if "graph_token" in r.get("sources", [])),
                "sparse_fts": sum(1 for r in filtered if "sparse_fts" in r.get("sources", [])),
                "semantic": sum(1 for r in filtered if "semantic" in r.get("sources", [])),
            },
            "cross_workspace_count": sum(1 for r in filtered if r.get("cross_workspace_refs")),
            "has_chain_results": intent.get("is_chain_query", False),
        },
        "level_3_next_actions": next_actions,
    }

    return {
        "total_found": len(filtered),
        "returned": len(filtered),
        "retrieval_summary": retrieval_summary,
        "progressive": progressive,
    }


def _project_matches(query_project: str, item_project: str) -> bool:
    """Check if a project query matches an item's project name.

    Uses normalized matching: splits on '-' and '_', then checks if the
    query matches the full name, any component (≥4 chars), or a concatenation
    of adjacent components.  Short components like 'api', 'back', 'web' are
    too generic to match alone — they must match the full name or a
    concatenated segment.
    """
    if not query_project or not item_project:
        return False
    q = query_project.lower().strip()
    p = item_project.lower().strip()
    if q == p:
        return True
    # Common infra/platform components that are too generic to match alone
    _GENERIC_COMPONENTS = {
        "api", "app", "web", "back", "front", "open", "cloud", "core",
        "base", "common", "service", "biz", "lib", "sdk", "data",
        "test", "main", "src", "res", "config", "util", "utils",
    }
    p_parts = p.replace("-", "_").split("_")
    # Full component match — only if component is specific enough
    if q in p_parts and q not in _GENERIC_COMPONENTS:
        return True
    # Concatenated adjacent component match (e.g. 'openapi' matches 'open_api')
    for i in range(len(p_parts)):
        for j in range(i + 2, min(i + 5, len(p_parts) + 1)):
            if "".join(p_parts[i:j]) == q:
                return True
    # Hyphenated query match (e.g. 'open-api' matches 'open_api')
    if "-" in q:
        q_parts = q.replace("-", "_").split("_")
        for i in range(len(p_parts)):
            if p_parts[i:i + len(q_parts)] == q_parts:
                return True
    return False


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
    merged = _rerank_symbol_like_matches(_suppress_semantic_only_noise(merged, query), query)
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


def memory_query_hybrid(workspace_file: str | Path, query: str, limit: int = 20, node_types: List[str] | None = None, config: Any = None, project: str = "") -> Dict[str, Any]:
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

    # Project filtering: when project is specified and matching results exist,
    # narrow the primary result set to that project instead of only boosting.
    if project:
        results = result.get("results", [])
        project_results = [r for r in results if _project_matches(project, r.get("node", {}).get("project", ""))]
        if project_results:
            for r in project_results:
                r["score"] = r.get("score", 0) * 2.0
                r["_project_boost"] = True
            project_results.sort(key=lambda x: x.get("score", 0), reverse=True)
            result["results"] = project_results
            # Rebuild summary fields so they match the filtered result set
            rebuild = _rebuild_summary_after_filter(project_results, intent)
            result["total_found"] = rebuild["total_found"]
            result["returned"] = rebuild["returned"]
            result["retrieval_summary"] = rebuild["retrieval_summary"]
            result["progressive"] = rebuild["progressive"]

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

        # Feign → API 自动关联：只关联查询直接匹配的方法，且路径足够具体（至少2段）
        linked_api = []
        if primary_intent == "feign" and filtered_feign:
            api_by_path = {}
            for c in contracts.get("api_contracts", []):
                p = c.get("path", "")
                # 路径至少2段（如 /api/users）才参与自动关联
                if p and len([s for s in p.split("/") if s]) >= 2:
                    api_by_path[p] = c
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

        if project:
            filtered_feign = [c for c in filtered_feign if _project_matches(project, c.get("project", ""))]
            filtered_mq = [c for c in filtered_mq if _project_matches(project, c.get("project", ""))]
            filtered_api = [c for c in filtered_api if _project_matches(project, c.get("project", ""))]

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
    elif "results" in result:
        result["matches"] = result["results"]

    result["results"] = _rerank_symbol_like_matches(result.get("results", []), query)
    result["matches"] = result["results"]

    # 确保 retrieval_summary 包含旧接口期望的字段
    if "retrieval_summary" in result:
        summary = result["retrieval_summary"]
        if "exact_matches" not in summary:
            summary["exact_matches"] = summary.get("source_distribution", {}).get("graph", 0)
        if "semantic_matches" not in summary:
            summary["semantic_matches"] = summary.get("source_distribution", {}).get("semantic", 0)

    # NEXT_PHASE: integrate freshness warnings into query results
    try:
        from ..freshness.status import IndexFreshnessService
        svc = IndexFreshnessService(workspace_file)
        banner = svc.banner()
        result["freshness"] = banner
        # D-01: Stale risk escalation - if freshness is stale/pending, add warning
        freshness_status = (banner.get("freshness", {}) or {}).get("status", "unknown")
        if freshness_status in ("stale", "pending"):
            from ..freshness.integration import freshness_action_hint, freshness_risk_escalation
            result["_freshness_warning"] = {
                "status": freshness_status,
                "hint": freshness_action_hint(freshness_status),
                "risk_escalation": freshness_risk_escalation(
                    result.get("intent_analysis", {}).get("risk_level", "low"),
                    freshness_status,
                ),
            }
    except Exception as exc:
        result["freshness"] = diag_entry(DIAG.UNKNOWN, exc=exc)

    # F-03: Record query metrics (best-effort)
    try:
        from ..metrics import MetricsCollector
        mc = MetricsCollector(workspace_file)
        mc.record("memory_query_hybrid", len(json.dumps(result, ensure_ascii=False)), unit="chars")
    except Exception:
        pass

    return result


def _filter_contracts_by_query(contracts: list, query: str, intent: str) -> list:
    """Filter contracts by query relevance with confidence scoring.

    Confidence levels (per ONTOLOGY.md §5.6):
    - 0.95: interface name exact match
    - 0.85: method name exact match
    - 0.60: token match in interface name
    - 0.30: token match in JSON dump
    - 0.10: fallback (no match, top-N returned with is_fallback=True)
    """
    if not contracts:
        return []

    query_lower = query.lower()
    tokens = tokenize(query_lower)
    scored_matches: list[tuple[float, str, dict]] = []  # (confidence, match_type, contract)

    for contract in contracts:
        contract_str = json.dumps(contract, ensure_ascii=False).lower()

        if intent == "feign" and "interface" in contract:
            interface_name = contract.get("interface", "").lower()
            # EntityValidator boost: 确认是 Feign 实体时提升置信度 (§5.1)
            is_feign = EntityValidator.is_feign_entity(interface_name)
            # 接口名精确匹配
            if query_lower in interface_name or interface_name in query_lower:
                scored_matches.append((0.97 if is_feign else 0.95, "interface_exact", contract))
                continue
            # 方法名精确匹配
            method_matched = False
            for m in contract.get("methods", []):
                if query_lower in m.get("method_name", "").lower():
                    scored_matches.append((0.85, "method_exact", contract))
                    method_matched = True
                    break
            if method_matched:
                continue
            # Token 匹配
            if any(token in interface_name for token in tokens):
                scored_matches.append((0.60, "token_match", contract))
        elif intent == "endpoint" and "path" in contract:
            path = contract.get("path", "").lower()
            controller = contract.get("controller", "").lower()
            if query_lower in path or query_lower in controller:
                scored_matches.append((0.90, "path_exact", contract))
            elif any(token in path or token in controller for token in tokens):
                scored_matches.append((0.60, "token_match", contract))
        else:
            # 通用匹配 — JSON 全文扫描
            if any(token in contract_str for token in tokens):
                scored_matches.append((0.30, "json_scan", contract))

    # 按置信度降序排列
    scored_matches.sort(key=lambda x: x[0], reverse=True)

    if scored_matches:
        result = []
        for confidence, match_type, contract in scored_matches[:20]:
            enriched = dict(contract)
            enriched["_confidence"] = confidence
            enriched["_match_type"] = match_type
            result.append(enriched)
        return result

    # 无匹配回退：返回 top-N，标记为 fallback
    fallback = []
    for contract in contracts[:10]:
        enriched = dict(contract)
        enriched["_confidence"] = 0.10
        enriched["_match_type"] = "fallback"
        enriched["_is_fallback"] = True
        fallback.append(enriched)
    return fallback


def memory_context(
    workspace_file: str | Path,
    name: str,
    max_depth: int = 2,
    project: str = "",
    view: str = "full",
    budget: str = "medium",
) -> Dict[str, Any]:
    _, store = load_context(workspace_file)
    lookup = memory_query_hybrid(workspace_file, name, limit=8, project=project)
    matches = [item.get("node", {}) for item in lookup.get("matches", []) if item.get("node")]
    if not matches:
        return {"name": name, "found": False, "matches": [], "lookup": _build_lookup_payload(lookup)}
    node = _best_match(matches, name)
    with GraphStore(store.graph_db_path) as graph:
        incoming = graph.neighbors(node["id"], direction="upstream", max_depth=max_depth, limit=100)
        outgoing = graph.neighbors(node["id"], direction="downstream", max_depth=max_depth, limit=100)
    # NEXT_PHASE: integrate reasoning risk patterns into context
    risk_patterns = []
    diagnostics: Dict[str, Any] = {}
    try:
        from ..reasoning.risk import RiskPatternEngine
        from ..storage.unified import UnifiedStore
        with UnifiedStore(store.graph_db_path) as unified:
            analyzer = RiskPatternEngine(unified, workspace_store=store)
            risks = analyzer.analyze_change_risk(node.get("id", ""))
            risk_patterns = [r.__dict__ if hasattr(r, "__dict__") else r for r in risks[:5]]
    except Exception as exc:
        diagnostics["risk_patterns"] = diag_entry(DIAG.UNAVAILABLE, exc=exc)

    # NEXT_PHASE: integrate freshness into context
    freshness = {}
    try:
        from ..freshness.status import IndexFreshnessService
        svc = IndexFreshnessService(workspace_file)
        freshness = svc.banner()
    except Exception as exc:
        diagnostics["freshness"] = diag_entry(DIAG.UNAVAILABLE, exc=exc)

    result = {
        "name": name,
        "found": True,
        "node": node,
        "incoming": incoming,
        "outgoing": outgoing,
        "lookup": _build_lookup_payload(lookup),
        "evidence_summary": _build_context_evidence_summary(incoming, outgoing),
        "progressive": _build_context_progressive_view(node, incoming, outgoing),
        "risk_patterns": risk_patterns,
        "freshness": freshness,
    }
    if diagnostics:
        result["_diagnostics"] = diagnostics
    if _is_compact_view(view):
        compact = _compact_context_result(result, budget=budget)
        gain = _measure_compact_gain(result, compact)
        log_token_gain(workspace_file, "memory_context", budget=budget, model="", raw_tokens=gain["raw_tokens"], compact_tokens=gain["compact_tokens"], view=view)
        return compact
    return result


def memory_symbol(
    workspace_file: str | Path,
    name: str,
    limit: int = 10,
    project: str = "",
    view: str = "full",
    budget: str = "medium",
) -> Dict[str, Any]:
    """Resolve a symbol name to graph nodes.

    When multiple nodes match (e.g. same class name in different modules),
    use ``project`` to disambiguate.  If ``project`` is empty but the query
    looks like a FQN (contains dots and a capitalised tail), the package
    segments are used to guess the project.
    """
    # FQN inference: cn.kaipuyun.cloud.openapi...ServiceImpl → try "openapi"
    inferred_project = project
    if not inferred_project and "." in name and not name.startswith("."):
        inferred_project = _infer_project_from_fqn(name, workspace_file)
    internal_limit = max(limit, min(max(limit * 3, 12), 50))

    lookup = memory_query_hybrid(
        workspace_file,
        name,
        limit=internal_limit,
        node_types=["Class", "Method", "Field", "FeignClient", "FeignMethod", "Endpoint", "MQTopic", "MQConsumer", "ConfigKey", "File"],
        project=inferred_project,
    )
    all_lookup_matches = list(lookup.get("matches", []) or [])
    if inferred_project:
        global_lookup = memory_query_hybrid(
            workspace_file,
            name,
            limit=internal_limit,
            node_types=["Class", "Method", "Field", "FeignClient", "FeignMethod", "Endpoint", "MQTopic", "MQConsumer", "ConfigKey", "File"],
            project="",
        )
        all_lookup_matches = list(global_lookup.get("matches", []) or all_lookup_matches)
    matches = [item.get("node", {}) for item in lookup.get("matches", []) if item.get("node")]

    # If inferred_project is known but no match found in that project,
    # try a direct graph lookup by class name + project
    if inferred_project and not any(_project_matches(inferred_project, m.get("project", "")) for m in matches):
        from ..graph import GraphStore
        store = load_context(workspace_file)[1]
        with GraphStore(store.graph_db_path) as g:
            # Extract class name from FQN (last segment)
            class_name = name.replace("#", ".").split(".")[-1]
            direct = g.find_nodes(class_name, types=["Class"], limit=50)
            project_nodes = [n for n in direct if _project_matches(inferred_project, n.get("project", ""))]
            if project_nodes:
                # Prepend project-matched nodes
                lookup.setdefault("matches", [])
                for node in project_nodes:
                    lookup["matches"].insert(0, {"node": node, "score": 999.0, "sources": ["direct_lookup"]})
                matches = [item.get("node", {}) for item in lookup.get("matches", []) if item.get("node")]
    if not matches:
        return {"name": name, "found": False, "matches": [], "lookup": _build_lookup_payload(lookup)}

    # If project is known, filter ALL results to that project
    if inferred_project:
        project_matches = [m for m in matches if _project_matches(inferred_project, m.get("project", ""))]
        if project_matches:
            matches = project_matches
        # Also filter the lookup matches list to stay consistent
        lookup_matches = lookup.get("matches", [])
        project_lookup = [m for m in lookup_matches if _project_matches(inferred_project, (m.get("node") or {}).get("project", ""))]
        if project_lookup:
            lookup["matches"] = project_lookup

    lookup["matches"] = _dedupe_symbol_display_matches(_rerank_symbol_like_matches(lookup.get("matches", []), name))
    matches = [item.get("node", {}) for item in lookup.get("matches", []) if item.get("node")]

    best = _best_match(matches, name)
    fallback_best = _pick_symbol_declaration_fallback(all_lookup_matches, name)
    if fallback_best and best.get("type") == "Field":
        best = fallback_best

    # Group remaining matches by project for disambiguation
    projects_seen: Dict[str, int] = {}
    for m in matches:
        p = m.get("project") or ""
        projects_seen[p] = projects_seen.get(p, 0) + 1

    filtered_lookup = lookup.get("matches", [])[:limit]
    result: Dict[str, Any] = {
        "name": name,
        "found": True,
        "best_match": best,
        "matches": filtered_lookup,
        "lookup": _build_lookup_payload(lookup),
    }
    if len(projects_seen) > 1:
        result["disambiguation"] = {
            "projects": projects_seen,
            "hint": "多个模块包含同名符号，用 project 参数或 FQN 消歧",
        }
    if _is_compact_view(view):
        compact = _compact_symbol_result(result, budget=budget)
        gain = _measure_compact_gain(result, compact)
        log_token_gain(workspace_file, "memory_symbol", budget=budget, model="", raw_tokens=gain["raw_tokens"], compact_tokens=gain["compact_tokens"], view=view)
        return compact
    return result


def _infer_project_from_fqn(fqn: str, workspace_file: str | Path) -> str:
    """Try to infer the project name from a fully-qualified class name.

    E.g.  cn.kaipuyun.cloud.openapi.biz.service.impl.website.safe.FooServiceImpl
    → segments = [cn, kaipuyun, cloud, openapi, biz, service, impl, ...]
    → try matching 'openapi' against known project names in the workspace.

    Scoring: prefer segments that appear as a distinct word-boundary in the
    project name (e.g. 'openapi' in 'ucap-cloud-open-api' splits on '-'
    and 'openapi' matches the concatenation of adjacent parts 'open'+'api').
    """
    parts = fqn.replace("#", ".").split(".")
    segments = [p for p in parts[:-1] if p and p[0].islower()]

    # Common Java package segments that are useless for project disambiguation
    _PACKAGE_STOPWORDS = {
        "cn", "com", "org", "net", "io", "app", "api", "biz", "service",
        "impl", "common", "core", "dto", "vo", "entity", "config", "util",
        "utils", "controller", "mapper", "dao", "repository", "model",
        "bean", "factory", "handler", "listener", "filter", "interceptor",
        "aspect", "annotation", "web", "rest", "rpc", "client", "server",
        "base", "lib", "sdk", "starter", "autoconfigure", "properties",
        "website", "safe", "back", "front", "admin", "manager", "task",
        "job", "schedule", "message", "mq", "cache", "data", "storage",
    }

    config, _store = load_context(workspace_file)
    projects = [s.name for s in config.services] if hasattr(config, "services") else []

    best_proj = ""
    best_score = 0
    for seg in reversed(segments):
        if len(seg) < 3 or seg in _PACKAGE_STOPWORDS:
            continue
        candidates: list[tuple[str, int]] = []
        for proj in projects:
            proj_lower = proj.lower()
            proj_parts = proj_lower.replace("-", "_").split("_")

            if seg == proj_lower:
                score = 100
            elif seg in proj_parts:
                score = 80
            else:
                matched = False
                for i in range(len(proj_parts)):
                    for j in range(i + 2, min(i + 5, len(proj_parts) + 1)):
                        if "".join(proj_parts[i:j]) == seg:
                            matched = True
                            break
                    if matched:
                        break
                if matched:
                    score = 70
                elif seg in proj_lower:
                    score = 50
                else:
                    continue
            candidates.append((proj, score))

        # Prefer unique matches: if only one project matches this segment, bonus +20
        if len(candidates) == 1:
            proj, score = candidates[0]
            score += 20
            if score > best_score:
                best_score = score
                best_proj = proj
        elif len(candidates) > 1:
            # Multiple projects match — pick highest score, but no uniqueness bonus
            for proj, score in candidates:
                if score > best_score:
                    best_score = score
                    best_proj = proj

        if best_score >= 90:
            break

    return best_proj


def memory_callers(
    workspace_file: str | Path,
    symbol: str,
    depth: int = 2,
    limit: int = 80,
    edge_type_filter: List[str] | None = None,
    project: str = "",
    view: str = "full",
    budget: str = "medium",
) -> Dict[str, Any]:
    info = memory_symbol(workspace_file, symbol, limit=8, project=project)
    if not info.get("found"):
        return {"symbol": symbol, "found": False, "callers": [], "lookup": info.get("lookup", {})}
    node = info["best_match"]
    et = edge_type_filter or preferred_edge_types("upstream")
    with GraphStore(load_context(workspace_file)[1].graph_db_path) as graph:
        edges = graph.neighbors(node["id"], direction="upstream", max_depth=depth, limit=limit, edge_types=et)
    callers = _filter_call_edges(edges, direction="upstream")[:limit]
    result = {
        "symbol": symbol,
        "found": True,
        "target": node,
        "depth": depth,
        "callers": callers,
        "chain_tree": _compress_chain_tree(callers),
        "chain_summary": _summarize_chain_edges(callers),
        "lookup": info.get("lookup", {}),
    }
    if _is_compact_view(view):
        compact = _compact_chain_result(result, direction="callers", budget=budget)
        gain = _measure_compact_gain(result, compact)
        log_token_gain(workspace_file, "memory_callers", budget=budget, model="", raw_tokens=gain["raw_tokens"], compact_tokens=gain["compact_tokens"], view=view)
        return compact
    return result


def memory_callees(
    workspace_file: str | Path,
    symbol: str,
    depth: int = 2,
    limit: int = 80,
    edge_type_filter: List[str] | None = None,
    project: str = "",
    view: str = "full",
    budget: str = "medium",
) -> Dict[str, Any]:
    info = memory_symbol(workspace_file, symbol, limit=8, project=project)
    if not info.get("found"):
        return {"symbol": symbol, "found": False, "callees": [], "lookup": info.get("lookup", {})}
    node = info["best_match"]
    et = edge_type_filter or preferred_edge_types("downstream")
    with GraphStore(load_context(workspace_file)[1].graph_db_path) as graph:
        edges = graph.neighbors(node["id"], direction="downstream", max_depth=depth, limit=limit, edge_types=et)
    callees = _filter_call_edges(edges, direction="downstream")[:limit]
    result = {
        "symbol": symbol,
        "found": True,
        "target": node,
        "depth": depth,
        "callees": callees,
        "chain_tree": _compress_chain_tree(callees),
        "chain_summary": _summarize_chain_edges(callees),
        "lookup": info.get("lookup", {}),
    }
    if _is_compact_view(view):
        compact = _compact_chain_result(result, direction="callees", budget=budget)
        gain = _measure_compact_gain(result, compact)
        log_token_gain(workspace_file, "memory_callees", budget=budget, model="", raw_tokens=gain["raw_tokens"], compact_tokens=gain["compact_tokens"], view=view)
        return compact
    return result


def memory_search_code(workspace_file: str | Path, query: str, scope: str = "", limit: int = 20, project: str = "") -> Dict[str, Any]:
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
        item_project = item.get("project", "")
        if project and not _project_matches(project, item_project):
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


def memory_discover(
    workspace_file: str | Path,
    limit: int = 50,
) -> Dict[str, Any]:
    """Discover hot commands and recommend next actions based on workspace state.

    Inspired by rtk's discover pattern:
    - Hot commands: most frequently used tools/commands
    - Recommended next actions: based on current workspace state
    - Command compression matrix: compact output patterns for common queries
    """
    config, store = load_context(workspace_file)
    events = store.read_jsonl_prefer_backend(SESSION_EVENTS_FILE, limit=max(limit, 200))

    # Analyze hot commands
    tool_counts: Dict[str, int] = {}
    recent_queries: list = []
    for event in events:
        if event.get("event_type") != "tool_call":
            continue
        payload = _event_payload(event)
        tool_name = str(payload.get("tool_name") or payload.get("name") or "")
        if tool_name:
            tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1
        query = payload.get("query", "") or payload.get("target", "") or payload.get("text", "")
        if query:
            recent_queries.append(query)

    hot_commands = sorted(tool_counts.items(), key=lambda x: -x[1])[:10]

    # Recommended next actions based on workspace state
    recommendations: list = []
    candidate_paths: list[dict[str, Any]] = []
    try:
        from .workspace import workspace_status
        status = workspace_status(workspace_file, view="compact", budget="medium")
        layers = status.get("memory_layers", {})
        if layers.get("L0", {}).get("count", 0) == 0:
            recommendations.append("还没有会话事件，建议先运行 `work-start` 启动工作流")
            candidate_paths.append(
                {
                    "candidate_type": "session_bootstrap",
                    "target": "work-start",
                    "status": "probable",
                    "weight": 0.76,
                    "why": "当前还没有会话事件，先启动工作流能尽快建立上下文轨迹。",
                    "next_action": "先运行 `work-start` 或 `mc_start` 启动任务",
                    "verification_cost": "low",
                }
            )
        if layers.get("L1", {}).get("count", 0) == 0:
            recommendations.append("还没有案例记忆，建议在完成关键操作后运行 `work-sync`")
            candidate_paths.append(
                {
                    "candidate_type": "memory_write",
                    "target": "L1_case_atom",
                    "status": "possible",
                    "weight": 0.7,
                    "why": "当前缺少案例记忆，补齐 case 沉淀可以提升后续复用价值。",
                    "next_action": "在关键阶段后运行 `work-sync` 或 `mc_sync`",
                    "verification_cost": "low",
                }
            )
        if layers.get("L2", {}).get("count", 0) == 0:
            recommendations.append("还没有任务空间，建议运行 `artifact create-task` 创建任务")
            candidate_paths.append(
                {
                    "candidate_type": "task_sync",
                    "target": "new-task-space",
                    "status": "probable",
                    "weight": 0.78,
                    "why": "当前缺少任务空间，先创建 task 能让长任务协作更稳定。",
                    "next_action": "运行 `artifact create-task` 或 `mc_sync(intent=...)`",
                    "verification_cost": "low",
                    "_learning_aliases": [
                        {"candidate_type": "task_sync", "target": "new-task-space"},
                    ],
                }
            )
    except Exception:
        pass

    if not candidate_paths:
        candidate_paths.append(
            {
                "candidate_type": "runtime_governance",
                "target": "continue-current-workflow",
                "status": "possible",
                "weight": 0.62,
                "why": "当前工作区状态整体正常，可继续沿现有工作流推进。",
                "next_action": "继续当前任务；必要时用 `mc_lookup` / `mc_analyze` 深挖",
                "verification_cost": "low",
            }
        )
    candidate_paths = apply_candidate_path_learning(workspace_file, candidate_paths)

    # Command compression matrix — compact aliases for common queries
    compression_matrix = {
        "quick_context": {"command": "mc_lookup", "mode": "auto", "view": "compact", "budget": "small"},
        "full_chain": {"command": "mc_lookup", "mode": "chain", "scope": "cross-service"},
        "impact_check": {"command": "mc_analyze", "depth": "quick"},
        "sync_progress": {
            "command": "mc_sync",
            "usage": "Provide `intent` for sniff sync, or `session_id` for case sync.",
            "required_one_of": ["intent", "session_id"],
        },
        "resume_work": {"command": "mc_resume"},
        "handoff_model": {"command": "mc_handoff"},
        "health_check": {"command": "mc_admin", "action": "health"},
        "audit_check": {"command": "mc_admin", "action": "audit"},
    }

    return {
        "workspace": config.workspace,
        "hot_commands": [{"tool": t, "count": c} for t, c in hot_commands],
        "recent_queries": recent_queries[:10],
        "recommendations": recommendations if recommendations else ["工作区状态正常，继续当前工作"],
        "candidate_paths": candidate_paths,
        "recommended_path": dict(candidate_paths[0]) if candidate_paths else {},
        "compression_matrix": compression_matrix,
    }


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


def _format_chain_endpoint(node: Dict[str, Any]) -> str:
    name = str(node.get("name", "") or "?")
    line = int(node.get("line", 0) or 0)
    return f"{name}:{line}" if line > 0 else name


def _format_compact_node_summary(node: Dict[str, Any]) -> str:
    node_type = str(node.get("type", "") or "").strip()
    name = str(node.get("name", "") or "?").strip()
    project = str(node.get("project", "") or "").strip()
    line = int(node.get("line", 0) or 0)
    parts = [part for part in (node_type, name) if part]
    text = " ".join(parts) if parts else name
    if project and line > 0:
        return f"{text} @ {project}:{line}"
    if project:
        return f"{text} @ {project}"
    if line > 0:
        return f"{text} @ line {line}"
    return text


def _build_edge_summary_lines(prefix: str, items: List[Dict[str, Any]], limit: int) -> List[str]:
    lines: List[str] = []
    for item in items[:limit]:
        text = str(item.get("text", "") or "").strip()
        if text:
            lines.append(f"{prefix}: {text}")
    return lines


def _summarize_chain_edges(edges: List[Dict[str, Any]]) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    type_counts: Dict[str, int] = {}
    for edge in edges:
        edge_type = str(edge.get("type", "") or "")
        type_counts[edge_type] = type_counts.get(edge_type, 0) + 1
        source = edge.get("source", {}) or {}
        target = edge.get("target", {}) or {}
        items.append(
            {
                "text": f"{_format_chain_endpoint(source)} --{edge_type}--> {_format_chain_endpoint(target)}",
                "type": edge_type,
                "depth": int(edge.get("depth", 0) or 0),
                "source": {
                    "name": source.get("name", ""),
                    "line": int(source.get("line", 0) or 0),
                    "project": source.get("project", ""),
                },
                "target": {
                    "name": target.get("name", ""),
                    "line": int(target.get("line", 0) or 0),
                    "project": target.get("project", ""),
                },
            }
        )
    return {
        "items": items,
        "total_edges": len(edges),
        "depth_reached": max((int(edge.get("depth", 0) or 0) for edge in edges), default=0),
        "type_counts": type_counts,
    }


def _compact_focus_edges(edges: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not edges:
        return []
    filtered = [
        edge for edge in edges
        if not (
            (edge.get("source", {}) or {}).get("name", "") == (edge.get("target", {}) or {}).get("name", "")
            and (edge.get("source", {}) or {}).get("project", "") == (edge.get("target", {}) or {}).get("project", "")
        )
    ]
    if not filtered:
        filtered = list(edges)
    structural_types = {"DECLARES", "CONTAINS", "IMPORTS"}
    if any(edge.get("type") not in structural_types for edge in filtered):
        focused = [edge for edge in filtered if edge.get("type") not in structural_types]
        if focused:
            return focused
    return filtered


def _compact_chain_result(result: Dict[str, Any], direction: str, budget: str = "medium") -> Dict[str, Any]:
    from .common import _budget_limits

    limits = _budget_limits(budget)
    target = result.get("target", {}) or {}
    lookup = result.get("lookup", {}) or {}
    entrypoints = lookup.get("entrypoints", []) or []
    summary = result.get("chain_summary", {}) or {}
    items = summary.get("items", []) or []
    summary_lines = [f"Target {_format_compact_node_summary(target)}"]
    summary_lines.extend(
        _build_edge_summary_lines("Caller" if direction == "callers" else "Callee", items, limits["steps"] + limits["events"])
    )
    return {
        "symbol": result.get("symbol", ""),
        "found": result.get("found", False),
        "direction": direction,
        "depth": result.get("depth", 0),
        "target": {
            "type": target.get("type", ""),
            "name": target.get("name", ""),
            "project": target.get("project", ""),
            "file_path": target.get("file_path", ""),
            "line": target.get("line", 0),
        },
        "chain_summary": {
            "items": items[: limits["steps"] + limits["events"]],
            "total_edges": summary.get("total_edges", 0),
            "depth_reached": summary.get("depth_reached", 0),
            "type_counts": summary.get("type_counts", {}),
        },
        "summary_lines": summary_lines,
        "lookup": {
            "query": lookup.get("query", ""),
            "retrieval_summary": lookup.get("retrieval_summary", {}),
            "entrypoints": [
                {
                    "type": (item.get("node", {}) or {}).get("type", ""),
                    "name": (item.get("node", {}) or {}).get("name", ""),
                    "project": (item.get("node", {}) or {}).get("project", ""),
                    "line": (item.get("node", {}) or {}).get("line", 0),
                    "exact_score": item.get("exact_score", 0),
                }
                for item in entrypoints[: limits["events"]]
            ],
        },
    }


def _compact_symbol_result(result: Dict[str, Any], budget: str = "medium") -> Dict[str, Any]:
    from .common import _budget_limits

    limits = _budget_limits(budget)
    best = result.get("best_match", {}) or {}
    matches = result.get("matches", []) or []
    compact_matches = []
    for item in matches[: limits["events"]]:
        node = item.get("node", {}) or {}
        compact_matches.append(
            {
                "type": node.get("type", ""),
                "name": node.get("name", ""),
                "project": node.get("project", ""),
                "line": node.get("line", 0),
                "score": round(float(item.get("score", item.get("exact_score", 0.0)) or 0.0), 4),
            }
        )
    summary_lines: List[str] = []
    if best:
        summary_lines.append(f"Best {_format_compact_node_summary(best)}")
    for item in compact_matches:
        summary_lines.append(f"Match {_format_compact_node_summary(item)} (score={item['score']})")
    payload = {
        "name": result.get("name", ""),
        "found": result.get("found", False),
        "best_match": {
            "type": best.get("type", ""),
            "name": best.get("name", ""),
            "project": best.get("project", ""),
            "file_path": best.get("file_path", ""),
            "line": best.get("line", 0),
        },
        "matches": compact_matches,
        "lookup": {
            "query": (result.get("lookup", {}) or {}).get("query", ""),
            "retrieval_summary": (result.get("lookup", {}) or {}).get("retrieval_summary", {}),
        },
        "summary_lines": summary_lines,
    }
    if result.get("disambiguation"):
        payload["disambiguation"] = result.get("disambiguation", {})
    return payload


def _compact_context_result(result: Dict[str, Any], budget: str = "medium") -> Dict[str, Any]:
    from .common import _budget_limits

    limits = _budget_limits(budget)
    node = result.get("node", {}) or {}
    incoming = result.get("incoming", []) or []
    outgoing = result.get("outgoing", []) or []
    incoming_summary = _summarize_chain_edges(_compact_focus_edges(incoming))
    outgoing_summary = _summarize_chain_edges(_compact_focus_edges(outgoing))
    lookup = result.get("lookup", {}) or {}
    summary_lines = [f"Node {_format_compact_node_summary(node)}"]
    summary_lines.extend(
        _build_edge_summary_lines("Incoming", incoming_summary.get("items", []), limits["steps"] + limits["events"])
    )
    summary_lines.extend(
        _build_edge_summary_lines("Outgoing", outgoing_summary.get("items", []), limits["steps"] + limits["events"])
    )
    return {
        "name": result.get("name", ""),
        "found": result.get("found", False),
        "node": {
            "type": node.get("type", ""),
            "name": node.get("name", ""),
            "project": node.get("project", ""),
            "file_path": node.get("file_path", ""),
            "line": node.get("line", 0),
        },
        "evidence_summary": result.get("evidence_summary", {}),
        "incoming_summary": {
            "items": incoming_summary.get("items", [])[: limits["steps"] + limits["events"]],
            "total_edges": incoming_summary.get("total_edges", 0),
            "depth_reached": incoming_summary.get("depth_reached", 0),
            "type_counts": incoming_summary.get("type_counts", {}),
        },
        "outgoing_summary": {
            "items": outgoing_summary.get("items", [])[: limits["steps"] + limits["events"]],
            "total_edges": outgoing_summary.get("total_edges", 0),
            "depth_reached": outgoing_summary.get("depth_reached", 0),
            "type_counts": outgoing_summary.get("type_counts", {}),
        },
        "summary_lines": summary_lines,
        "lookup": {
            "query": lookup.get("query", ""),
            "retrieval_summary": lookup.get("retrieval_summary", {}),
            "entrypoints": [
                {
                    "type": (item.get("node", {}) or {}).get("type", ""),
                    "name": (item.get("node", {}) or {}).get("name", ""),
                    "project": (item.get("node", {}) or {}).get("project", ""),
                    "line": (item.get("node", {}) or {}).get("line", 0),
                    "exact_score": item.get("exact_score", 0),
                }
                for item in (lookup.get("entrypoints", []) or [])[: limits["events"]]
            ],
        },
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
    matches = _dedupe_symbol_display_matches(result.get(match_key, []))[:limit]
    return {
        "query": result.get("query", result.get("target", result.get("name", ""))),
        "retrieval_summary": result.get("retrieval_summary", {}),
        "entrypoints": [
            {
                "node": item.get("node", {}),
                "retrieval_sources": item.get("retrieval_sources", item.get("sources", [])),
                "exact_score": item.get("exact_score", item.get("rrf_score", item.get("score", 0.0))),
                "semantic_score": item.get("semantic_score", item.get("score", 0.0) if "semantic" in item.get("sources", []) else 0.0),
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
