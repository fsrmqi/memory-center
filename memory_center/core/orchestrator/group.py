from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..registry import resolve_group
from .common import (
    _build_progressive_levels,
    _rrf,
    _unknown_static_analysis_risks,
    load_context,
    tokenize,
)
from .query import (
    _build_lookup_payload,
    _query_node_priority,
    _sort_target_types,
    memory_query,
)


def group_status(group: str, home: str | Path | None = None) -> Dict[str, Any]:
    from .workspace import workspace_status

    resolved = resolve_group(group, home)
    workspaces = []
    totals: Dict[str, int] = {"files": 0, "symbols": 0, "apis": 0, "feigns": 0, "mq": 0, "cases": 0}
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


def group_query(
    group: str,
    query: str,
    limit: int = 20,
    node_types: List[str] | None = None,
    home: str | Path | None = None,
) -> Dict[str, Any]:
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
            node_id = node.get("id") or f"{node.get('type', 'unknown')}:{node.get('name', 'unknown')}:{workspace_ref}:{rank}"
            key = f"{workspace_ref}:{node_id}"
            current = merged.setdefault(key, {
                "workspace_ref": workspace_ref,
                "workspace": workspace_name,
                "node": node,
                "neighbors": item.get("neighbors", []),
                "rrf_score": 0.0,
                "semantic_score": 0.0,
                "best_rank": rank,
                "retrieval_sources": [],
            })
            current["rrf_score"] += float(item.get("exact_score", _rrf(rank)))
            current["semantic_score"] = max(current["semantic_score"], float(item.get("semantic_score", 0.0)))
            current["best_rank"] = min(current["best_rank"], rank)
            if "exact" not in current["retrieval_sources"]:
                current["retrieval_sources"].append("exact")

    for entry in workspace_results:
        for hit in entry["result"].get("semantic_hits", []):
            _merge_group_semantic_hit(merged, entry["workspace_ref"], entry["workspace"], hit, entry["result"].get("matches", []), target_types)

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
    from .impact import memory_impact

    group_data = _load_group_data(resolve_group(group, home).get("members", []))
    if not group_data:
        return {
            "group": group,
            "target": target,
            "direction": direction,
            "found": False,
            "risk_level": "unknown",
            "impacted_workspaces": [],
            "confirmed_impacts": [],
            "probable_impacts": [],
            "possible_impacts": [],
            "impacts": [],
            "related_bridges": [],
            "lookup": {"query": target, "retrieval_summary": {"exact_matches": 0, "semantic_matches": 0, "total_matches": 0}, "entrypoints": []},
            "progressive": _build_group_impact_progressive_view(group, target, [], [], []),
            "unknown_risks": _unknown_static_analysis_risks(),
        }

    target_types = _resolve_group_target_types(target)
    all_impacts: List[Dict[str, Any]] = []
    workspace_refs: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    for member in group_data:
        workspace_file = member.get("workspace_file", "")
        name = member.get("name", "")
        workspace_refs.append({"name": name, "workspace": member.get("workspace", "")})
        try:
            impact = memory_impact(workspace_file, target, direction=direction, max_depth=max_depth)
            if impact.get("found"):
                for category, label in [
                    ("confirmed_impacts", "confirmed"),
                    ("probable_impacts", "probable"),
                    ("possible_impacts", "possible"),
                ]:
                    for item in impact.get(category, []):
                        all_impacts.append({
                            **item,
                            "_workspace": name,
                            "_workspace_file": workspace_file,
                            "_confidence_band": label,
                        })
        except Exception as exc:
            errors.append({"name": name, "workspace_file": workspace_file, "error": str(exc)})

    bridges = _build_group_bridges(group_data, query=target, limit=50)
    impact_bridges = _filter_impact_bridges(bridges, target, target_types, limit=50)
    sorted_bridges = _sort_bridges(impact_bridges, target_types)

    filtered_records = _filter_group_impact_records(all_impacts, target_types)
    # Exclude non-call edges like CONTAINS, DECLARES that don't represent real impact
    filtered_records = [r for r in filtered_records if r.get("type", "") not in {"CONTAINS", "DECLARES"}]
    sorted_records = _sort_group_impact_records(filtered_records, target_types)

    impacted_projects = sorted({
        item.get("source", {}).get("project", "") or item.get("_workspace", "")
        for item in sorted_records
        if item.get("source", {}).get("project") or item.get("_workspace")
    })
    high_risk_types = {"DTO", "Field", "FeignClient", "FeignMethod", "MQTopic", "MQConsumer", "Endpoint", "ConfigKey"}
    has_high_risk = any(
        item.get("source", {}).get("type", "") in high_risk_types
        or item.get("target", {}).get("type", "") in high_risk_types
        for item in sorted_records
    )
    if has_high_risk or len(impacted_projects) >= 3:
        risk_level = "high"
    elif sorted_records:
        risk_level = "medium"
    else:
        risk_level = "low"

    evidence_summary = _build_group_impact_evidence_summary(sorted_records, sorted_bridges)

    # Split impacts by confidence band, wrapping each in {kind, impact} structure
    confirmed_impacts = [_wrap_graph_impact(item, "confirmed") for item in sorted_records if item.get("_confidence_band") == "confirmed"]
    probable_impacts = [_wrap_graph_impact(item, "probable") for item in sorted_records if item.get("_confidence_band") == "probable"]
    possible_impacts = [_wrap_graph_impact(item, "possible") for item in sorted_records if item.get("_confidence_band") == "possible"]

    impacted_workspaces = sorted({
        item.get("_workspace", "")
        for item in sorted_records
        if item.get("_workspace")
    })

    # Build lookup payload from merged per-workspace queries
    lookup_entries: List[Dict[str, Any]] = []
    for member in group_data:
        try:
            member_lookup = memory_query(member.get("workspace_file", ""), target, limit=5)
            for match in member_lookup.get("matches", []):
                lookup_entries.append({
                    "node": match.get("node", {}),
                    "retrieval_sources": match.get("retrieval_sources", []),
                    "exact_score": match.get("exact_score", match.get("rrf_score", 0.0)),
                    "semantic_score": match.get("semantic_score", 0.0),
                    "workspace_ref": member.get("name", ""),
                    "workspace": member.get("workspace", ""),
                })
        except Exception:
            continue
    lookup_payload = {
        "query": target,
        "retrieval_summary": {
            "exact_matches": sum(1 for item in lookup_entries if "exact" in item.get("retrieval_sources", [])),
            "semantic_matches": sum(1 for item in lookup_entries if "semantic" in item.get("retrieval_sources", [])),
            "total_matches": len(lookup_entries),
        },
        "entrypoints": lookup_entries,
    }

    return {
        "group": group,
        "target": target,
        "direction": direction,
        "max_depth": max_depth,
        "found": bool(sorted_records or sorted_bridges),
        "risk_level": risk_level,
        "impacted_projects": impacted_projects,
        "impacted_workspaces": impacted_workspaces,
        "target_types": target_types,
        "confirmed_impacts": confirmed_impacts,
        "probable_impacts": probable_impacts,
        "possible_impacts": possible_impacts,
        "impacts": sorted_records[:50],
        "related_bridges": sorted_bridges[:30],
        "evidence_summary": evidence_summary,
        "lookup": lookup_payload,
        "progressive": _build_group_impact_progressive_view(group, target, sorted_records, workspace_refs, sorted_bridges, impacted_workspaces),
        "unknown_risks": _unknown_static_analysis_risks(),
        "errors": errors,
    }


# ---- private helpers: data loading -----------------------------------------


def _wrap_graph_impact(record: Dict[str, Any], band: str) -> Dict[str, Any]:
    return {
        "kind": "graph",
        "impact": {
            "type": record.get("type", ""),
            "source": record.get("source", {}),
            "target": record.get("target", {}),
        },
        "confidence": float(record.get("confidence", 0)),
        "_workspace": record.get("_workspace", ""),
        "_confidence_band": band,
    }


def _load_group_data(members: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    loaded: List[Dict[str, Any]] = []
    for member in members:
        workspace_file = member.get("workspace_file", "")
        name = member.get("name", "")
        if not workspace_file:
            continue
        try:
            config, store = load_context(workspace_file)
            loaded.append({
                "name": name,
                "workspace_ref": name,
                "workspace": config.workspace,
                "workspace_file": str(workspace_file),
                "services": [s.__dict__ for s in config.services],
                "feigns": store.read_json_prefer_backend("feign-index.json", []),
                "apis": store.read_json_prefer_backend("api-index.json", []),
                "mq": store.read_json_prefer_backend("mq-index.json", []),
                "configs": store.read_json_prefer_backend("config-index.json", []),
            })
        except Exception:
            continue
    return loaded


def _build_group_bridges(group_data: List[Dict[str, Any]], **_kwargs: Any) -> List[Dict[str, Any]]:
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
                bridges.append({
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
                })
            for method in feign.get("methods", []):
                for api in apis:
                    if method.get("http_method") == api.get("http_method") and method.get("path") == api.get("path"):
                        bridges.append({
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
                        })

    for topic, consumers in mq_topics.items():
        if not topic:
            continue
        for consumer in consumers:
            for cfg in config_values.get(topic, []):
                bridges.append({
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
                })
        if len(consumers) >= 2:
            primary = consumers[0]
            for other in consumers[1:]:
                bridges.append({
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
                })

    for key, entries in config_keys.items():
        if len(entries) < 2:
            continue
        primary = entries[0]
        for other in entries[1:]:
            bridges.append({
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
            })

    deduped: Dict[str, Dict[str, Any]] = {}
    for bridge in bridges:
        key = "|".join([
            bridge.get("type", ""),
            bridge.get("source_workspace", ""),
            bridge.get("source_project", ""),
            bridge.get("target_workspace", ""),
            bridge.get("target_project", ""),
            bridge.get("summary", ""),
        ])
        deduped[key] = bridge
    return list(deduped.values())


def _count_bridges(bridges: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for bridge in bridges:
        bridge_type = bridge.get("type", "unknown")
        counts[bridge_type] = counts.get(bridge_type, 0) + 1
    return counts


def _filter_bridges(bridges: List[Dict[str, Any]], query: str, limit: int) -> List[Dict[str, Any]]:
    if not bridges:
        return []
    query_tokens = set(tokenize(query))
    matched = []
    for bridge in bridges:
        haystack = json.dumps(bridge, ensure_ascii=False).lower()
        if any(token in haystack for token in query_tokens):
            matched.append(bridge)
    matched.sort(key=lambda item: (-float(item.get("confidence", 0)), item.get("summary", "")))
    return matched[:limit]


def _filter_impact_bridges(
    bridges: List[Dict[str, Any]],
    target: str,
    target_types: List[str],
    limit: int,
) -> List[Dict[str, Any]]:
    if not bridges:
        return []
    target_lower = target.lower()
    target_tokens = set(tokenize(target))
    matched: List[Dict[str, Any]] = []
    for bridge in bridges:
        bridge_type = bridge.get("type", "")
        summary_lower = (bridge.get("summary", "") or "").lower()
        # Match by bridge type falling into target_types categories
        bridge_category = _bridge_type_category(bridge_type)
        if target_lower in summary_lower or any(token in summary_lower for token in target_tokens):
            matched.append({**bridge, "_match_kind": "token"})
            continue
        if bridge_category in target_types:
            matched.append({**bridge, "_match_kind": "type_token"})
            continue
    matched.sort(key=lambda item: (
        0 if item.get("_match_kind") == "exact_name" else 1 if item.get("_match_kind") == "type_token" else 2,
        -float(item.get("confidence", 0.0)),
    ))
    return matched[:limit]


def _bridge_type_category(bridge_type: str) -> str:
    category_map = {
        "FEIGN_SERVICE": "FeignClient",
        "FEIGN_ENDPOINT": "Endpoint",
        "MQ_TOPIC_CONFIG": "MQTopic",
        "MQ_TOPIC_SHARED": "MQTopic",
        "CONFIG_KEY_SHARED": "ConfigKey",
    }
    return category_map.get(bridge_type, "")


def _bridge_types_for_target(bridge: Dict[str, Any], target_types: List[str]) -> str:
    bridge_type = bridge.get("type", "")
    category = _bridge_type_category(bridge_type)
    if category in target_types:
        return category
    return bridge_type if bridge_type in target_types else "other"


def _sort_bridges(bridges: List[Dict[str, Any]], target_types: List[str]) -> List[Dict[str, Any]]:
    return sorted(bridges, key=lambda item: _bridge_sort_key(item, target_types))


def _bridge_sort_key(bridge: Dict[str, Any], target_types: List[str]) -> tuple:
    bridge_type = bridge.get("type", "")
    priority = _bridge_priority(bridge_type, target_types)
    type_order = _bridge_type_order(bridge_type)
    confidence = float(bridge.get("confidence", 0.0))
    return (
        priority,
        type_order,
        -confidence,
        bridge.get("summary", ""),
    )


def _bridge_type_order(bridge_type: str) -> int:
    order = {
        "FEIGN_ENDPOINT": 0, "FEIGN_SERVICE": 1,
        "MQ_TOPIC_CONFIG": 0, "MQ_TOPIC_SHARED": 1,
        "CONFIG_KEY_SHARED": 0,
    }
    return order.get(bridge_type, 10)


def _bridge_priority(bridge_type: str, target_types: List[str]) -> int:
    priority_map: Dict[str, int] = {}
    types = set(target_types)
    if {"FeignClient", "FeignMethod", "Endpoint"} & types:
        priority_map.update({"FEIGN_ENDPOINT": 0, "FEIGN_SERVICE": 1, "FeignClient": 2, "FeignMethod": 3, "Endpoint": 4, "Class": 5, "Method": 6, "File": 7})
    if {"MQTopic", "MQConsumer"} & types:
        priority_map.update({"MQ_TOPIC_CONFIG": 0, "MQ_TOPIC_SHARED": 1, "MQTopic": 2, "MQConsumer": 3, "ConfigKey": 4, "Class": 5, "File": 6})
    if "ConfigKey" in types:
        priority_map.update({"CONFIG_KEY_SHARED": 0, "ConfigKey": 1, "Class": 2, "File": 3})
    if not priority_map:
        priority_map.update({"Class": 0, "Method": 1, "Field": 2, "File": 3})
    if bridge_type in priority_map:
        return priority_map[bridge_type]
    return priority_map.get("other", 20)


def _resolve_group_target_types(target: str, target_types: List[str] | None = None) -> List[str]:
    return _sort_target_types(list(_infer_target_types(target)))


def _infer_target_types(target: str) -> set:
    resolved: set = set()
    target_lower = target.lower()
    # Hyphenated names that don't look like service/app names are likely topics/queues
    service_indicators = {"service", "api", "common", "gateway", "server", "app", "web", "ui", "frontend", "backend", "admin", "portal"}
    hyphen_like = "-" in target_lower and not any(ind in target_lower for ind in service_indicators)
    topic_like = hyphen_like or any(token in target_lower for token in ["topic", "kafka", "rocketmq", "consumer", "producer", "listener"])
    if "feign" in target_lower:
        resolved.update({"FeignClient", "FeignMethod"})
    if target_lower.startswith("/") or any(token in target_lower for token in ["controller", "endpoint"]):
        resolved.add("Endpoint")
    if topic_like:
        resolved.add("MQTopic")
    if "." in target_lower and not topic_like and "feign" not in target_lower and not target_lower.startswith("/"):
        resolved.add("ConfigKey")
    if topic_like and "MQTopic" in resolved:
        resolved.discard("ConfigKey")
    return resolved


def _group_query_match_key(item: Dict[str, Any], target_types: List[str]) -> tuple:
    node = item.get("node", {})
    node_type = node.get("type", "") or item.get("node_type", "")
    priority = _query_node_priority(node_type, target_types)
    sources = set(item.get("retrieval_sources", []))
    hybrid_rank = 0 if {"exact", "semantic"} <= sources else 1 if "exact" in sources else 2 if "semantic" in sources else 3
    return (
        priority,
        hybrid_rank,
        -float(item.get("rrf_score", item.get("exact_score", 0.0))),
        -float(item.get("semantic_score", 0.0)),
        int(item.get("best_rank", 9999)),
        node.get("name", "") or item.get("node_name", ""),
    )


def _find_group_query_neighbors(workspace_matches: List[Dict[str, Any]], node_id: str) -> List[Dict[str, Any]]:
    for match in workspace_matches:
        match_node_id = match.get("node_id", "") or match.get("node", {}).get("id", "")
        if match_node_id == node_id:
            return match.get("neighbors", [])
    return []


def _merge_group_semantic_hit(
    merged: Dict[str, Dict[str, Any]],
    workspace_ref: str,
    workspace_name: str,
    hit: Dict[str, Any],
    workspace_matches: List[Dict[str, Any]],
    target_types: List[str],
) -> None:
    node_id = hit.get("node_id", "")
    if not node_id:
        return
    node = hit.get("node", {})
    key = f"{workspace_name}:{node_id}"
    existing = merged.get(key)
    if existing:
        existing["semantic_score"] = max(existing.get("semantic_score", 0.0), float(hit.get("score", 0.0)))
        if workspace_name not in existing.get("seen_in_workspaces", []):
            existing.setdefault("seen_in_workspaces", []).append(workspace_name)
        return
    neighbors = _find_group_query_neighbors(workspace_matches, node_id)
    merged[key] = {
        "workspace_ref": workspace_ref,
        "workspace": workspace_name,
        "node": node,
        "neighbors": neighbors,
        "exact_score": 0.0,
        "semantic_score": float(hit.get("score", 0.0)),
        "best_rank": 1000,
        "retrieval_sources": ["semantic"],
        "seen_in_workspaces": [workspace_name],
    }


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
    impact_records: List[Dict[str, Any]],
    workspace_refs: List[Dict[str, Any]],
    bridges: List[Dict[str, Any]] = [],
    impacted_workspaces: List[str] = [],
) -> Dict[str, Any]:
    confirmed_count = sum(1 for item in impact_records if item.get("_confidence_band") == "confirmed")
    probable_count = sum(1 for item in impact_records if item.get("_confidence_band") == "probable")
    possible_count = sum(1 for item in impact_records if item.get("_confidence_band") == "possible")
    workspace_names = sorted({
        item.get("_workspace", "")
        for item in impact_records
        if item.get("_workspace")
    })
    return _build_progressive_levels(
        {
            "group": group,
            "target": target,
            "member_count": len(workspace_refs),
            "total_impacts": len(impact_records),
            "impacted_workspace_count": len(workspace_names),
            "impacted_workspaces": workspace_names,
        },
        {
            "confirmed_count": confirmed_count,
            "probable_count": probable_count,
            "possible_count": possible_count,
            "workspaces_queried": [ref.get("name", "") for ref in workspace_refs],
            "type_distribution": _type_distribution_from_impacts(impact_records),
            "top_bridges": [
                {
                    "type": item.get("type", ""),
                    "summary": item.get("summary", ""),
                    "confidence": item.get("confidence", 0.0),
                }
                for item in bridges[:5]
            ],
        },
        {
            "impacted_workspaces": workspace_names,
            "next_action": "Inspect each impacted workspace individually with memory_context and memory_impact.",
            "impact_preview": [
                _group_impact_record_label(item)
                for item in impact_records[:8]
            ],
        },
    )


def _group_impact_record_label(item: Dict[str, Any]) -> str:
    source = item.get("source", {})
    target_node = item.get("target", {})
    edge_type = item.get("type", "")
    workspace = item.get("_workspace", "")
    band = item.get("_confidence_band", "")
    source_name = source.get("name", "")
    target_name = target_node.get("name", "")
    if source_name and target_name:
        return f"[{workspace}] {source_name} --{edge_type}--> {target_name} ({band})"
    if source_name:
        return f"[{workspace}] {source_name} ({band})"
    if target_name:
        return f"[{workspace}] {target_name} ({band})"
    return f"[{workspace}] {edge_type} ({band})"


def _build_group_impact_evidence_summary(
    impact_records: List[Dict[str, Any]],
    bridges: List[Dict[str, Any]],
) -> Dict[str, Any]:
    confirmed = sum(1 for item in impact_records if item.get("_confidence_band") == "confirmed")
    probable = sum(1 for item in impact_records if item.get("_confidence_band") == "probable")
    possible = sum(1 for item in impact_records if item.get("_confidence_band") == "possible")
    edge_types = sorted({
        item.get("type", "")
        for item in impact_records
        if item.get("type")
    })
    bridge_types_set = sorted({
        item.get("type", "")
        for item in bridges
        if item.get("type")
    })
    combined_types = sorted(set(edge_types) | set(bridge_types_set))
    bridge_workspaces = sorted({item.get("source_workspace_name", "") or item.get("workspace_name", "") for item in bridges if (item.get("source_workspace_name", "") or item.get("workspace_name", ""))})
    return {
        "confirmed_count": confirmed,
        "probable_count": probable,
        "possible_count": possible,
        "bridge_types": combined_types,
        "bridge_evidence_count": len(bridges),
        "bridge_workspaces": bridge_workspaces,
    }


def _filter_group_impact_records(
    records: List[Dict[str, Any]],
    target_types: List[str],
) -> List[Dict[str, Any]]:
    if not target_types:
        return records
    type_set = set(target_types)
    filtered: List[Dict[str, Any]] = []
    for record in records:
        source_type = record.get("source", {}).get("type", "")
        target_type = record.get("target", {}).get("type", "")
        edge_type = record.get("type", "")
        if source_type in type_set or target_type in type_set:
            filtered.append(record)
            continue
        if any(
            graph_type in edge_type
            for graph_type in _graph_edge_types_for_target(target_types)
        ):
            filtered.append(record)
    return filtered if filtered else records


def _sort_group_impact_records(
    records: List[Dict[str, Any]],
    target_types: List[str],
) -> List[Dict[str, Any]]:
    return sorted(records, key=lambda item: _group_impact_record_key(item, target_types))


def _group_impact_record_key(record: Dict[str, Any], target_types: List[str]) -> tuple:
    band = record.get("_confidence_band", "")
    band_priority = 0 if band == "confirmed" else 1 if band == "probable" else 2
    source_type = record.get("source", {}).get("type", "")
    target_type = record.get("target", {}).get("type", "")
    type_priority = _bridge_priority(source_type, target_types)
    confidence = -float(record.get("confidence", 0.0))
    return (band_priority, type_priority, confidence, record.get("_workspace", ""))


def _graph_edge_types_for_target(target_types: List[str]) -> List[str]:
    edge_types: List[str] = []
    types = set(target_types)
    if types & {"FeignClient", "FeignMethod"}:
        edge_types.extend(["IMPLEMENTS_FEIGN", "CALLS_SERVICE"])
    if "Endpoint" in types:
        edge_types.extend(["HANDLES_ENDPOINT", "CALLS_SERVICE"])
    if types & {"MQTopic", "MQConsumer"}:
        edge_types.extend(["CONSUMES_TOPIC", "PRODUCES_TOPIC"])
    if "ConfigKey" in types:
        edge_types.extend(["READS_CONFIG", "INJECTS_BEAN"])
    if not edge_types:
        edge_types.extend(["CALLS_METHOD", "CALLS_SERVICE", "READS_FIELD", "IMPORTS"])
    return edge_types


def _graph_edge_priority(edge_type: str, target_types: List[str]) -> int:
    edge_priorities: Dict[str, int] = {}
    types = set(target_types)
    if types & {"FeignClient", "FeignMethod"}:
        edge_priorities.update({"IMPLEMENTS_FEIGN": 0, "CALLS_SERVICE": 1, "CALLS_METHOD": 2})
    if "Endpoint" in types:
        edge_priorities.update({"HANDLES_ENDPOINT": 0, "CALLS_SERVICE": 1})
    if types & {"MQTopic", "MQConsumer"}:
        edge_priorities.update({"CONSUMES_TOPIC": 0, "PRODUCES_TOPIC": 1})
    if "ConfigKey" in types:
        edge_priorities.update({"READS_CONFIG": 0, "INJECTS_BEAN": 1})
    if not edge_priorities:
        edge_priorities.update({"CALLS_METHOD": 0, "CALLS_SERVICE": 1, "READS_FIELD": 2, "IMPORTS": 3})
    return edge_priorities.get(edge_type, 10)


def _type_distribution(items: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in items:
        node_type = item.get("node_type", "") or item.get("type", "") or "unknown"
        counts[node_type] = counts.get(node_type, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def _type_distribution_from_impacts(items: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in items:
        source_type = item.get("source", {}).get("type", "")
        if source_type:
            counts[source_type] = counts.get(source_type, 0) + 1
        target_type = item.get("target", {}).get("type", "")
        if target_type:
            counts[target_type] = counts.get(target_type, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
