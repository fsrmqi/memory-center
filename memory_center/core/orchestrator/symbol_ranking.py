"""符号锚点选择与相似命中的重排、去重、噪音抑制。

从 query.py 按独立职责拆出的检索排序辅助(ADR-0002):纯函数,不持有 workspace 状态。
注意: shared.py 中存在同名的旧版 _project_matches(缺少连字符查询匹配),行为有差异,
以本模块版本为准,后续再统一。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .ranking import _node_type_priority


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


def _node_matches_symbol_query(node: dict[str, Any], query: str) -> bool:
    target = _normalize_symbol_name(query).lower()
    if not target:
        return False
    name = str(node.get("name", "") or "").strip()
    if not name:
        return False
    short = name.split(".")[-1].lower()
    return short == target or name.lower() == target


def _has_exact_lookup_source(item: dict[str, Any]) -> bool:
    sources = set(item.get("sources", []) or item.get("retrieval_sources", []) or [])
    return bool({"exact", "graph_exact", "graph_token", "sparse_fts", "sparse_bm25", "direct_lookup"} & sources)


def _pick_symbol_anchor(items: list[dict[str, Any]], query: str) -> dict[str, Any]:
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


def _pick_symbol_declaration_fallback(items: list[dict[str, Any]], query: str) -> dict[str, Any]:
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


def _symbol_rank_bucket(node: dict[str, Any], query: str, anchor: dict[str, Any]) -> int:
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


def _rerank_symbol_like_matches(items: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    if not _looks_like_class_symbol_query(query):
        return items
    if not any(
        (item.get("node", item).get("type") == "Class") and _node_matches_symbol_query(item.get("node", item), query)
        for item in items
    ):
        return items
    anchor = _pick_symbol_anchor(items, query)

    def key(item: dict[str, Any]) -> tuple:
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


def _dedupe_symbol_display_matches(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not items:
        return items

    def dedupe_key(item: dict[str, Any]) -> tuple[str, str, str] | None:
        node = item.get("node", item)
        node_type = node.get("type", "")
        if node_type not in {"Method", "FeignMethod"}:
            return None
        return (
            str(node.get("project", "") or ""),
            str(node.get("file_path", "") or ""),
            str(node.get("name", "") or ""),
        )

    def type_priority(item: dict[str, Any]) -> tuple[int, float]:
        node = item.get("node", item)
        node_type = node.get("type", "")
        priority = {"FeignMethod": 0, "Method": 1}
        return (
            priority.get(node_type, 10),
            -float(item.get("score", item.get("exact_score", 0.0)) or 0.0),
        )

    deduped: list[dict[str, Any]] = []
    seen: dict[tuple[str, str, str], int] = {}
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


def _suppress_semantic_only_noise(items: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    strong_exact_hit = any(_has_exact_lookup_source(item) and _node_matches_symbol_query(item.get("node", item), query) for item in items)
    if not strong_exact_hit:
        return items
    adjusted: list[dict[str, Any]] = []
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
    type_counts: dict[str, int] = {}
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

    result = {
        "total_found": len(filtered),
        "returned": len(filtered),
        "retrieval_summary": retrieval_summary,
        "progressive": progressive,
    }
    return result


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
