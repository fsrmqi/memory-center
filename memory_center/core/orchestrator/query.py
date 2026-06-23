from __future__ import annotations

import json
import copy
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List

import yaml

from ..graph import GraphStore, node_id
from ..rules import match_rules
from ..schemas import with_schema
from ..semantic import semantic_index_stats, semantic_query
from ..ontology import EntityValidator
from ..observability import observe_operation
from ..result_types import attach_facade_metadata
from ..quality import build_quality_summary
from ..diagnostics import DIAG, diag_entry, safe_reason
from ..verification.heuristics import apply_candidate_path_learning
from ..tracking import log_token_gain
from ..walkthrough import runner as _walkthrough_runner
from ..walkthrough import operations as _walkthrough_operations
from .common import (
    SESSION_EVENTS_FILE,
    _best_match,
    _build_progressive_levels,
    _budget_limits,
    _event_payload,
    _filter_call_edges,
    _is_compact_view,
    _node_type_priority,
    _render_ref_label,
    _resolve_memory_ref,
    _rrf,
    load_context,
    preferred_edge_types,
    summarize_chain_edges,
    tokenize,
)
from .compact import _measure_compact_gain

METHOD_WALKTHROUGH_SCHEMA_VERSION = _walkthrough_runner.METHOD_WALKTHROUGH_SCHEMA_VERSION
_METHOD_WALKTHROUGH_CACHE_TTL_SECONDS = _walkthrough_runner.DEFAULT_CACHE_TTL_SECONDS
_METHOD_WALKTHROUGH_CACHE_MAX_ITEMS = _walkthrough_runner.DEFAULT_CACHE_MAX_ITEMS
_METHOD_WALKTHROUGH_CACHE = _walkthrough_runner.default_walkthrough_cache()


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


@observe_operation(
    "memory_query_hybrid",
    workspace_resolver=lambda args, kwargs: args[0] if args else kwargs["workspace_file"],
    tags_resolver=lambda args, kwargs: {"limit": kwargs.get("limit", args[2] if len(args) > 2 else 20)},
)
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
    freshness_banner: Dict[str, Any]
    try:
        from ..freshness.status import IndexFreshnessService

        freshness_banner = IndexFreshnessService(workspace_file).banner()
    except Exception as exc:
        freshness_banner = diag_entry(DIAG.UNKNOWN, exc=exc)
    freshness_input = (
        freshness_banner.get("freshness", {})
        if isinstance(freshness_banner, dict)
        else {}
    )
    try:
        from ..verification.heuristics import load_retrieval_source_weights

        learned_weights = load_retrieval_source_weights(
            workspace_file,
            intent=str(intent.get("primary_intent", "general") or "general"),
        )
    except Exception:
        learned_weights = {}

    with GraphStore(store.graph_db_path) as graph:
        result = hybrid_retrieve(
            graph=graph,
            workspace_file=str(workspace_file),
            query=query,
            config=config,
            node_types=node_types,
            limit=limit,
            freshness=freshness_input,
            learned_weights=learned_weights,
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
        else:
            # No results match the project filter — return empty but consistent
            empty_rebuild = _rebuild_summary_after_filter([], intent)
            result["results"] = []
            result["total_found"] = 0
            result["returned"] = 0
            result["retrieval_summary"] = empty_rebuild["retrieval_summary"]
            result["progressive"] = empty_rebuild["progressive"]

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

        # Feign → API 自动关联：只关联查询直接匹配的方法，且路径足够具体
        linked_api = []
        if primary_intent == "feign" and filtered_feign:
            api_by_path = {}
            for c in contracts.get("api_contracts", []):
                p = c.get("path", "")
                # 使用 EntityValidator 验证路径特异性（≥2段）
                validation = EntityValidator.validate_endpoint_path(p)
                if validation["is_specific"]:
                    api_by_path[p] = c
            query_lower_local = query.lower()
            for fc in filtered_feign:
                for m in fc.get("methods", []):
                    method_name = m.get("method_name", "").lower()
                    m_path = m.get("path", "")
                    # 只关联查询直接匹配的方法
                    if query_lower_local in method_name or method_name in query_lower_local:
                        if m_path and m_path in api_by_path:
                            matched_api = dict(api_by_path[m_path])
                            matched_api["_association"] = "feign_method_path"
                            matched_api["_association_confidence"] = 0.85
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
        banner = freshness_banner
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

    freshness_status = str(((result.get("freshness", {}) or {}).get("freshness", {}) or {}).get("status", "unknown"))
    quality_evidence = []
    for item in result.get("results", []) or []:
        sources = set(item.get("sources", []) or item.get("retrieval_sources", []) or [])
        quality_evidence.append({
            "confidence": item.get("score", 0.0),
            "evidence_type": "fact" if sources & {"exact", "graph_exact", "direct_lookup"} else "inferred",
        })
    result["_quality"] = build_quality_summary(quality_evidence, freshness_status=freshness_status)
    return attach_facade_metadata(
        result,
        operation="memory_query_hybrid",
        result_kind="lookup",
        evidence_level="hybrid_indexed",
    )


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
            enriched["_semantic_strength"] = _contract_semantic_strength(confidence)
            enriched["_match_reason"] = _contract_match_reason(match_type, contract, query)
            result.append(enriched)
        return result

    # 无匹配回退：返回 top-N，标记为 fallback
    fallback = []
    for contract in contracts[:10]:
        enriched = dict(contract)
        enriched["_confidence"] = 0.10
        enriched["_match_type"] = "fallback"
        enriched["_is_fallback"] = True
        enriched["_semantic_strength"] = "derived"
        enriched["_match_reason"] = "无精确匹配，返回候选契约作为参考"
        fallback.append(enriched)
    return fallback


def _contract_semantic_strength(confidence: float) -> str:
    """Map contract confidence to semantic strength."""
    if confidence >= 0.90:
        return "fact"
    if confidence >= 0.60:
        return "inferred"
    return "derived"


def _contract_match_reason(match_type: str, contract: dict, query: str) -> str:
    """Generate human-readable match reason for a contract."""
    if match_type == "interface_exact":
        iface = contract.get("interface", "")
        return '接口名 [' + str(iface) + '] 与查询 [' + str(query) + '] 精确匹配'
    if match_type == "method_exact":
        methods = [m.get("method_name", "") for m in contract.get("methods", [])]
        matched = [m for m in methods if query.lower() in m.lower()]
        return '方法名 [' + str(matched[0] if matched else '?') + '] 与查询 [' + str(query) + '] 匹配'
    if match_type == "path_exact":
        path = contract.get("path", "")
        return '路径 [' + str(path) + '] 与查询 [' + str(query) + '] 匹配'
    if match_type == "token_match":
        return '查询词与契约字段部分匹配'
    if match_type == "json_scan":
        return '查询词在契约全文扫描中匹配'
    if match_type == "fallback":
        return '无精确匹配，返回候选契约作为参考'
    return '匹配类型: ' + match_type


def memory_context(
    workspace_file: str | Path,
    name: str,
    max_depth: int = 2,
    project: str = "",
    view: str = "full",
    budget: str = "medium",
) -> Dict[str, Any]:
    _, store = load_context(workspace_file)
    symbol_info = memory_symbol(workspace_file, name, limit=8, project=project)
    if not symbol_info.get("found"):
        return {"name": name, "found": False, "matches": [], "lookup": symbol_info.get("lookup", {})}
    node = symbol_info.get("best_match", {}) or {}
    with GraphStore(store.graph_db_path) as graph:
        incoming = graph.neighbors(node["id"], direction="upstream", max_depth=max_depth, limit=100)
        outgoing = graph.neighbors(node["id"], direction="downstream", max_depth=max_depth, limit=100)
    # Integrate unified reasoning patterns into context (C-07)
    reasoning: Dict[str, Any] = {"patterns": [], "transitive": [], "risk": []}
    diagnostics: Dict[str, Any] = {}
    try:
        from ..reasoning.integration import run_reasoning_patterns, summarize_reasoning
        reasoning = run_reasoning_patterns(
            str(workspace_file),
            target_id=node.get("id", ""),
            target_name=name,
            intent="context",
        )
    except Exception as exc:
        diagnostics["reasoning"] = diag_entry(DIAG.UNAVAILABLE, exc=exc)
    risk_patterns = reasoning.get("risk", [])

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
        "lookup": symbol_info.get("lookup", {}),
        "project_scope": _build_project_scope(project, node),
        "project_evidence": _build_project_evidence(symbol_info.get("matches", []), node, project),
        "evidence_summary": _build_context_evidence_summary(incoming, outgoing),
        "progressive": _build_context_progressive_view(node, incoming, outgoing),
        "risk_patterns": risk_patterns,
        "freshness": freshness,
        "_reasoning": reasoning,
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
    project_evidence = _build_project_evidence(filtered_lookup, best, inferred_project, limit=5)
    result: Dict[str, Any] = {
        "name": name,
        "found": True,
        "best_match": best,
        "matches": filtered_lookup,
        "lookup": _build_augmented_lookup_payload(lookup, anchor_node=best, project_evidence=project_evidence),
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
        "project_scope": _build_project_scope(project, node),
        "project_evidence": _build_project_evidence(info.get("matches", []), node, project),
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
        "project_scope": _build_project_scope(project, node),
        "project_evidence": _build_project_evidence(info.get("matches", []), node, project),
        "lookup": info.get("lookup", {}),
    }
    if _is_compact_view(view):
        compact = _compact_chain_result(result, direction="callees", budget=budget)
        gain = _measure_compact_gain(result, compact)
        log_token_gain(workspace_file, "memory_callees", budget=budget, model="", raw_tokens=gain["raw_tokens"], compact_tokens=gain["compact_tokens"], view=view)
        return compact
    return result


def memory_method_walkthrough(
    workspace_file: str | Path,
    symbol: str,
    depth: int = 4,
    limit: int = 80,
    project: str = "",
    view: str = "full",
    budget: str = "medium",
    report_level: str = "standard",
    _allow_workspace_escalation: bool = True,
) -> Dict[str, Any]:
    """Build a method-level walkthrough from indexed Java evidence.

    This is intentionally evidence-bounded: it explains indexed method calls,
    DTO field reads, config/data-resource hints, and graph downstream edges.
    It does not pretend to execute Java control flow.
    """
    def _lookup_provider(ws: Path, sym: str, proj: str) -> Dict[str, Any]:
        return memory_symbol(ws, sym, limit=5, project=proj).get("lookup", {}) or {}

    def _escalation_runner(**call_kwargs: Any) -> Dict[str, Any]:
        return _try_escalated_method_walkthrough(
            call_kwargs["workspace_file"],
            call_kwargs["symbol"],
            call_kwargs["depth"],
            call_kwargs["limit"],
            call_kwargs["project"],
            call_kwargs["view"],
            call_kwargs["budget"],
            call_kwargs["report_level"],
            current_result=call_kwargs.get("current_result"),
            allow=True,
        )

    return _walkthrough_runner.build_walkthrough_result(
        workspace_file,
        symbol,
        depth=depth,
        limit=limit,
        project=project,
        view=view,
        budget=budget,
        report_level=report_level,
        allow_workspace_escalation=_allow_workspace_escalation,
        cache=_METHOD_WALKTHROUGH_CACHE,
        lookup_provider=_lookup_provider,
        escalation_runner=_escalation_runner,
    )


def memory_walkthrough_health(
    workspace_file: str | Path,
    symbol: str = "",
    project: str = "",
    report_level: str = "standard",
) -> Dict[str, Any]:
    """Check method walkthrough readiness and output contract for a workspace."""
    return _walkthrough_operations.build_walkthrough_health(
        workspace_file, symbol=symbol, project=project, report_level=report_level,
        walkthrough_provider=memory_method_walkthrough, cache=_METHOD_WALKTHROUGH_CACHE,
    )


def memory_eval_walkthrough_quality(
    workspace_file: str | Path,
    symbol: str,
    project: str = "",
    report_level: str = "standard",
) -> Dict[str, Any]:
    """Evaluate whether a method walkthrough result is agent-ready."""
    return _walkthrough_operations.evaluate_walkthrough(
        workspace_file, symbol, project=project, report_level=report_level,
        walkthrough_provider=memory_method_walkthrough,
    )


def memory_export_walkthrough_artifact(
    workspace_file: str | Path,
    symbol: str,
    project: str = "",
    report_level: str = "deep",
    title: str = "",
) -> Dict[str, Any]:
    """Export a method walkthrough Markdown artifact under artifacts/walkthroughs."""
    return _walkthrough_operations.export_walkthrough(
        workspace_file, symbol, project=project, report_level=report_level,
        title=title, walkthrough_provider=memory_method_walkthrough,
    )



# === Walkthrough helper shims =============================================
# These thin delegators preserve backward-compatible underscore names that
# tests and other modules import from `orchestrator.query`, while the real
# implementation lives in `memory_center.core.walkthrough`.
from ..walkthrough import answer as _wt_answer
from ..walkthrough import continuations as _wt_continuations
from ..walkthrough import escalation as _wt_escalation
from ..walkthrough import risks as _wt_risks
from ..walkthrough import symbols as _wt_symbols
from .common import SESSION_EVENTS_FILE as _WT_SESSION_EVENTS_FILE


def _walkthrough_recent_bypass_feedback(store: Any, limit: int = 200) -> Dict[str, Any]:
    return _wt_escalation.walkthrough_recent_bypass_feedback(store, _WT_SESSION_EVENTS_FILE, limit=limit)


def _resolve_walkthrough_workspace_input(workspace_file: str | Path) -> Path:
    return _wt_escalation.resolve_walkthrough_workspace_input(workspace_file)


def _walkthrough_index_signature(store: Any) -> Dict[str, float]:
    return _wt_escalation.walkthrough_index_signature(store)


def _method_walkthrough_cache_key(
    workspace_file: str | Path,
    symbol: str,
    depth: int,
    limit: int,
    project: str,
    view: str,
    budget: str,
    report_level: str,
    store: Any,
) -> str:
    return json.dumps(
        {
            "workspace_file": str(Path(workspace_file).expanduser().resolve()),
            "symbol": symbol,
            "depth": depth,
            "limit": limit,
            "project": project,
            "view": view,
            "budget": budget,
            "report_level": report_level,
            "index_signature": _walkthrough_index_signature(store),
        },
        sort_keys=True,
        ensure_ascii=False,
    )


def _method_walkthrough_fields_contract() -> Dict[str, Any]:
    return _wt_answer.method_walkthrough_fields_contract()


def _try_escalated_method_walkthrough(
    workspace_file: str | Path,
    symbol: str,
    depth: int,
    limit: int,
    project: str,
    view: str,
    budget: str,
    report_level: str,
    current_result: Dict[str, Any] | None,
    allow: bool,
) -> Dict[str, Any]:
    if not allow:
        return {}
    candidate = _wt_escalation.find_parent_or_covering_workspace(workspace_file)
    if not candidate:
        return {}
    candidate_path = str(candidate)
    current_path = str(Path(workspace_file).expanduser().resolve())
    if candidate_path == current_path:
        return {}
    try:
        escalated = memory_method_walkthrough(
            candidate_path,
            symbol,
            depth=depth,
            limit=limit,
            project=project,
            view="full",
            budget=budget,
            report_level=report_level,
            _allow_workspace_escalation=False,
        )
    except Exception as exc:
        if current_result is not None:
            current_result["workspace_escalation"] = _wt_escalation.build_workspace_escalation_status(
                workspace_file,
                status="candidate_failed",
                candidate_workspace=candidate_path,
                reason=str(exc),
            )
        return {}
    if not escalated.get("found"):
        return {}
    if current_result is not None and _wt_escalation.walkthrough_quality_score(escalated) <= _wt_escalation.walkthrough_quality_score(current_result):
        return {}
    escalated["workspace_escalation"] = _wt_escalation.build_workspace_escalation_status(
        workspace_file,
        status="escalated",
        candidate_workspace=candidate_path,
        reason="父级或覆盖当前项目的聚合 workspace 返回了更完整的跨服务 walkthrough。",
    )
    escalated["answer_markdown"] = _render_method_walkthrough_answer(escalated, candidate_path, report_level=report_level)
    if _is_compact_view(view):
        compact = _compact_method_walkthrough_result(escalated, budget=budget)
        compact["workspace_escalation"] = escalated["workspace_escalation"]
        compact["answer_markdown"] = escalated["answer_markdown"]
        return compact
    return escalated


def _find_parent_or_covering_workspace(workspace_file: str | Path) -> Path | None:
    return _wt_escalation.find_parent_or_covering_workspace(workspace_file)


def _registry_covering_workspaces(current_ws: Path, current_root: Path) -> List[Path]:
    return _wt_escalation.registry_covering_workspaces(current_ws, current_root)


def _registry_group_sibling_workspaces(current_ws: Path) -> List[Path]:
    return _wt_escalation.registry_group_sibling_workspaces(current_ws)


def _path_is_within(path: Path, maybe_parent: Path) -> bool:
    return _wt_escalation.path_is_within(path, maybe_parent)


def _walkthrough_quality_score(result: Dict[str, Any]) -> int:
    return _wt_escalation.walkthrough_quality_score(result)


def _build_workspace_escalation_status(
    workspace_file: str | Path,
    status: str,
    candidate_workspace: str = "",
    reason: str = "",
) -> Dict[str, Any]:
    return _wt_escalation.build_workspace_escalation_status(workspace_file, status, candidate_workspace=candidate_workspace, reason=reason)


def _parse_method_walkthrough_symbol(symbol: str) -> Dict[str, str]:
    return _wt_symbols.parse_method_walkthrough_symbol(symbol)


def _find_method_symbol_entry(symbols: List[Dict[str, Any]], parsed: Dict[str, str], project: str = "") -> Dict[str, Any]:
    return _wt_symbols.find_method_symbol_entry(symbols, parsed, project=project)


def _build_file_abs_path_map(config: Any, store: Any) -> Dict[tuple[str, str], str]:
    return _wt_symbols.build_file_abs_path_map(config, store)


def _resolve_indexed_abs_path(file_abs_map: Dict[tuple[str, str], str], project: str, file_path: str) -> str:
    return _wt_symbols.resolve_indexed_abs_path(file_abs_map, project, file_path)


def _build_method_local_steps(method_calls, dto_field_usages, feigns):
    return _wt_continuations.build_method_local_steps(method_calls, dto_field_usages, feigns)


def _build_method_feign_continuations(entry, method_name, method_calls, feigns, apis, symbols, file_abs_map):
    return _wt_continuations.build_method_feign_continuations(entry, method_name, method_calls, feigns, apis, symbols, file_abs_map)


def _build_service_impl_continuations(symbols, entry, method_calls, file_abs_map=None, feigns=None, apis=None):
    return _wt_continuations.build_service_impl_continuations(symbols, entry, method_calls, file_abs_map=file_abs_map, feigns=feigns, apis=apis)


def _build_same_class_method_continuations(symbols, entry, method_name, file_abs_map, feigns, apis):
    return _wt_continuations.build_same_class_method_continuations(symbols, entry, method_name, file_abs_map, feigns, apis)


def _detect_unqualified_same_class_calls(abs_path: str, owner_method: str, class_methods: set[str]) -> List[str]:
    return _wt_symbols.detect_unqualified_same_class_calls(abs_path, owner_method, class_methods)


def _extract_java_method_body(text: str, method_name: str) -> str:
    return _wt_symbols.extract_java_method_body(text, method_name)


def _matching_brace_end_runtime(text: str, open_pos: int) -> int:
    return _wt_symbols.matching_brace_end_runtime(text, open_pos)


def _summarize_dto_field_filters(dto_usages: List[Dict[str, Any]]) -> Dict[str, Any]:
    return _wt_continuations.summarize_dto_field_filters(dto_usages)


def _classify_dto_field_rule_groups(dto_usages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return _wt_continuations.classify_dto_field_rule_groups(dto_usages)


def _find_method_span_lines(abs_path: str, method_name: str) -> Dict[str, int]:
    return _wt_symbols.find_method_span_lines(abs_path, method_name)


def _line_number_at_offset(text: str, offset: int) -> int:
    return _wt_symbols.line_number_at_offset(text, offset)


def _find_receiver_impl_method(symbols, receiver_type, method_name, project):
    return _wt_symbols.find_receiver_impl_method(symbols, receiver_type, method_name, project)


def _dedupe_feign_continuations(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return _wt_continuations.dedupe_feign_continuations(items)


def _build_method_walkthrough_next_actions(feign_continuations, downstream_summary, local_service_continuations=None, same_class_continuations=None):
    return _wt_continuations.build_method_walkthrough_next_actions(feign_continuations, downstream_summary, local_service_continuations=local_service_continuations, same_class_continuations=same_class_continuations)


def _compact_method_walkthrough_result(result: Dict[str, Any], budget: str = "medium") -> Dict[str, Any]:
    return _wt_answer.compact_method_walkthrough_result(result, budget=budget, cache_ttl_seconds=_METHOD_WALKTHROUGH_CACHE_TTL_SECONDS)


def _render_method_walkthrough_answer(result, workspace_file, report_level: str = "standard") -> str:
    return _wt_answer.render_method_walkthrough_answer(result, workspace_file, report_level=report_level)


def _load_method_walkthrough_template(workspace_file):
    return _wt_answer.load_method_walkthrough_template(workspace_file)


def _method_walkthrough_template_context(result: Dict[str, Any], report_level: str = "standard") -> Dict[str, str]:
    return _wt_answer.method_walkthrough_template_context(result, report_level=report_level)


def _method_walkthrough_read_targets_text(result: Dict[str, Any]) -> str:
    return _wt_answer.method_walkthrough_read_targets_text(result)


def _method_walkthrough_rule_groups_text(result: Dict[str, Any]) -> str:
    return _wt_answer.method_walkthrough_rule_groups_text(result)


def _format_rule_group_lines(continuation: Dict[str, Any]) -> List[str]:
    return _wt_answer.format_rule_group_lines(continuation)


def _build_glossary_hits(workspace_file, result: Dict[str, Any]) -> List[Dict[str, Any]]:
    return _wt_answer.build_glossary_hits(workspace_file, result)


def _load_walkthrough_glossary(workspace_file) -> Dict[str, Any]:
    return _wt_answer.load_walkthrough_glossary(workspace_file)


def _collect_walkthrough_terms(result: Dict[str, Any]) -> set[str]:
    return _wt_answer.collect_walkthrough_terms(result)


def _build_walkthrough_performance_risks(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    return _wt_risks.build_walkthrough_performance_risks(result)


def _steps_to_calls(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [step for step in steps if step.get("kind") == "method_call"]


def _build_data_scope_guards(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    return _wt_risks.build_data_scope_guards(result)


def _extract_java_method_body_from_path(abs_path: str, method_name: str) -> str:
    return _wt_symbols.extract_java_method_body_from_path(abs_path, method_name)


def _build_walkthrough_diff_context(config: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    return _wt_risks.build_walkthrough_diff_context(config, result)


def _build_walkthrough_index_freshness(store: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    return _wt_risks.build_walkthrough_index_freshness(_wt_escalation.walkthrough_index_signature(store), result)


def _git_changed_abs_paths(root: Path) -> set[str]:
    return _wt_risks.git_changed_abs_paths(root)


def _collect_result_abs_paths(result: Dict[str, Any]) -> List[str]:
    return _wt_risks.collect_result_abs_paths(result)


def _build_walkthrough_branch_outline(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    return _wt_risks.build_walkthrough_branch_outline(result)


def _extract_java_case_labels(abs_path: str, method_name: str) -> List[str]:
    return _wt_symbols.extract_java_case_labels(abs_path, method_name)


def _build_method_walkthrough_mermaid(result: Dict[str, Any]) -> str:
    return _wt_risks.build_method_walkthrough_mermaid(result)


def _format_glossary_hits(items): return _wt_answer.format_glossary_hits(items)
def _format_risk_items(items): return _wt_answer.format_risk_items(items)
def _format_diff_context(diff): return _wt_answer.format_diff_context(diff)
def _format_index_freshness(freshness): return _wt_answer.format_index_freshness(freshness)
def _format_branch_outline(outlines): return _wt_answer.format_branch_outline(outlines)
def _format_anti_patterns(items): return _wt_answer.format_anti_patterns(items)


def _dedupe_risk_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return _wt_risks.dedupe_risk_items(items)


def _default_method_walkthrough_template(report_level: str = "standard") -> str:
    return _wt_answer.default_method_walkthrough_template(report_level)


def _normalize_report_level(report_level: str) -> str:
    return _wt_answer.normalize_report_level(report_level)


def _build_method_walkthrough_agent_policy() -> Dict[str, Any]:
    return _wt_answer.build_method_walkthrough_agent_policy()


def _build_method_walkthrough_anti_patterns() -> List[Dict[str, str]]:
    return _wt_answer.build_method_walkthrough_anti_patterns()


def _select_compact_method_steps(local_steps, limits):
    return _wt_answer.select_compact_method_steps(local_steps, limits)


def _build_method_walkthrough_summary_lines(target, local_steps, local_service_continuations, same_class_continuations, feigns, downstream, limits):
    return _wt_answer.build_method_walkthrough_summary_lines(target, local_steps, local_service_continuations, same_class_continuations, feigns, downstream, limits)


def _display_method_path(item: Dict[str, Any]) -> str:
    return _wt_answer.display_method_path(item)


# === End walkthrough helper shims =========================================


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


def _compact_node_evidence(item: Dict[str, Any]) -> Dict[str, Any]:
    node = item.get("node", item) or {}
    return {
        "type": node.get("type", ""),
        "name": node.get("name", ""),
        "project": node.get("project", ""),
        "file_path": node.get("file_path", ""),
        "line": node.get("line", 0),
        "score": round(float(item.get("score", item.get("exact_score", 0.0)) or 0.0), 4),
    }


def _build_project_scope(requested_project: str, anchor: Dict[str, Any]) -> Dict[str, Any]:
    anchor_project = str(anchor.get("project", "") or "")
    requested = str(requested_project or "").strip()
    return {
        "requested_project": requested,
        "anchor_project": anchor_project,
        "uses_cross_project_anchor": bool(requested and anchor_project and not _project_matches(requested, anchor_project)),
    }


def _build_project_evidence(items: List[Dict[str, Any]], anchor: Dict[str, Any], requested_project: str, limit: int = 5) -> List[Dict[str, Any]]:
    requested = str(requested_project or "").strip()
    if not requested:
        return []
    anchor_id = str(anchor.get("id", "") or "")
    evidence: List[Dict[str, Any]] = []
    for item in items:
        node = item.get("node", item) or {}
        if not _project_matches(requested, str(node.get("project", "") or "")):
            continue
        if anchor_id and str(node.get("id", "") or "") == anchor_id:
            continue
        evidence.append(_compact_node_evidence(item))
    return evidence[:limit]


def _build_lookup_entrypoint(item: Dict[str, Any], *, role: str = "") -> Dict[str, Any]:
    node = item.get("node", {}) or {}
    payload = {
        "node": node,
        "retrieval_sources": item.get("retrieval_sources", item.get("sources", [])),
        "exact_score": item.get("exact_score", item.get("rrf_score", item.get("score", 0.0))),
        "semantic_score": item.get("semantic_score", item.get("score", 0.0) if "semantic" in item.get("sources", []) else 0.0),
        "workspace_ref": item.get("workspace_ref", ""),
        "workspace": item.get("workspace", ""),
    }
    if role:
        payload["role"] = role
    return payload


def _node_to_lookup_item(node: Dict[str, Any], *, role: str, score: float = 0.0, sources: List[str] | None = None) -> Dict[str, Any]:
    return {
        "node": node,
        "score": score,
        "exact_score": score,
        "sources": sources or [],
        "retrieval_sources": sources or [],
        "role": role,
    }


def _build_augmented_lookup_payload(
    result: Dict[str, Any],
    *,
    anchor_node: Dict[str, Any] | None = None,
    project_evidence: List[Dict[str, Any]] | None = None,
    match_key: str = "matches",
    limit: int = 5,
) -> Dict[str, Any]:
    matches = _dedupe_symbol_display_matches(result.get(match_key, []))[:limit]
    entrypoints: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_signatures: set[tuple[str, str, str, int]] = set()

    def add_entry(item: Dict[str, Any], role: str = "") -> None:
        node = item.get("node", {}) or {}
        node_id = str(node.get("id", "") or f"{node.get('type','')}::{node.get('project','')}::{node.get('name','')}")
        signature = (
            str(node.get("type", "") or ""),
            str(node.get("project", "") or ""),
            str(node.get("name", "") or ""),
            int(node.get("line", 0) or 0),
        )
        if node_id in seen_ids:
            return
        if signature in seen_signatures:
            return
        seen_ids.add(node_id)
        seen_signatures.add(signature)
        entrypoints.append(_build_lookup_entrypoint(item, role=role or item.get("role", "")))

    if anchor_node:
        add_entry(_node_to_lookup_item(anchor_node, role="anchor", score=999.0, sources=["symbol_anchor"]), role="anchor")
    for evidence in (project_evidence or [])[:limit]:
        add_entry(
            _node_to_lookup_item(
                evidence,
                role="project_evidence",
                score=float(evidence.get("score", 0.0) or 0.0),
                sources=["project_scope"],
            ),
            role="project_evidence",
        )
    for item in matches:
        add_entry(item)

    return {
        "query": result.get("query", result.get("target", result.get("name", ""))),
        "retrieval_summary": result.get("retrieval_summary", {}),
        "entrypoints": entrypoints[:limit],
    }


def _summarize_chain_edges(edges: List[Dict[str, Any]]) -> Dict[str, Any]:
    return summarize_chain_edges(edges)


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
    project_evidence = result.get("project_evidence", []) or []
    if result.get("project_scope", {}).get("uses_cross_project_anchor"):
        summary_lines.append(
            f"Project scope {result.get('project_scope', {}).get('requested_project', '')} uses anchor {target.get('project', '')}"
        )
    for evidence in project_evidence[: limits["events"]]:
        summary_lines.append(f"Project evidence: {_format_compact_node_summary(evidence)}")
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
        "project_scope": result.get("project_scope", {}),
        "project_evidence": project_evidence[: limits["events"]],
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
    from ..reasoning.integration import compact_reasoning_view

    limits = _budget_limits(budget)
    node = result.get("node", {}) or {}
    incoming = result.get("incoming", []) or []
    outgoing = result.get("outgoing", []) or []
    incoming_summary = _summarize_chain_edges(_compact_focus_edges(incoming))
    outgoing_summary = _summarize_chain_edges(_compact_focus_edges(outgoing))
    lookup = result.get("lookup", {}) or {}
    summary_lines = [f"Node {_format_compact_node_summary(node)}"]
    project_evidence = result.get("project_evidence", []) or []
    if result.get("project_scope", {}).get("uses_cross_project_anchor"):
        summary_lines.append(
            f"Project scope {result.get('project_scope', {}).get('requested_project', '')} uses anchor {node.get('project', '')}"
        )
    for evidence in project_evidence[: limits["events"]]:
        summary_lines.append(f"Project evidence: {_format_compact_node_summary(evidence)}")
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
        "project_scope": result.get("project_scope", {}),
        "project_evidence": project_evidence[: limits["events"]],
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
        "_reasoning": compact_reasoning_view(result.get("_reasoning", {}), limit=2),
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
    return _build_augmented_lookup_payload(result, match_key=match_key, limit=limit)


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
