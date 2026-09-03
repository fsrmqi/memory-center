"""Call graph and reference navigation APIs separated from query facade."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from .lookup_shared import NavigationLookupPort, build_search_progressive, compress_chain_tree, summarize_chain

def _confidence(edges: list[dict[str, Any]], minimum: float, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    threshold = max(0.0, min(1.0, float(minimum or 0.0))); meta = {"requested_min_confidence": threshold, "applied_min_confidence": threshold, "fallback_to_low_confidence": False}
    if threshold <= 0: return edges[:limit], meta
    filtered = [edge for edge in edges if float(edge.get("confidence", 0.0) or 0.0) >= threshold]
    if filtered or not edges: return filtered[:limit], meta
    meta.update({"applied_min_confidence": 0.0, "fallback_to_low_confidence": True}); return edges[:limit], meta

def traverse(workspace_file: str | Path, symbol: str, *, direction: str, depth: int = 2, limit: int = 80, edge_type_filter: list[str] | None = None, project: str = "", view: str = "full", budget: str = "medium", min_confidence: float = 0.85, deps: NavigationLookupPort) -> dict[str, Any]:
    from memory_center.core.storage.runtime import RuntimeStore
    from memory_center.core.observability.tracking import log_token_gain
    info = deps.symbol_resolver(workspace_file, symbol, limit=8, project=project)
    key = "callers" if direction == "upstream" else "callees"
    if not info.get("found"): return {"symbol": symbol, "found": False, key: [], "lookup": info.get("lookup", {})}
    node = info["best_match"]; types = edge_type_filter or deps.preferred_edges(direction)
    with RuntimeStore(deps.load_context(workspace_file)[1].graph_db_path) as graph:
        edges = graph.traverse_edges(node["id"], direction=direction, max_depth=depth, limit=limit, edge_types=types)
    edges = deps.filter_edges(edges, direction=direction); selected, meta = _confidence(edges, min_confidence, limit)
    result = {"symbol": symbol, "found": True, "target": node, "depth": depth, key: selected, "chain_tree": compress_chain_tree(selected), "chain_summary": summarize_chain(selected), "project_scope": deps.build_project_scope(project, node), "project_evidence": deps.project_evidence(info.get("matches", []), node, project), "confidence_filter": meta, "lookup": info.get("lookup", {})}
    if deps.is_compact(view):
        compact = deps.compact_chain(result, direction=key, budget=budget); gain = deps.measure_compact(result, compact)
        log_token_gain(workspace_file, f"memory_{key}", budget=budget, model="", raw_tokens=gain["raw_tokens"], compact_tokens=gain["compact_tokens"], view=view); return compact
    return result


def search_code(workspace_file: str | Path, query: str, *, scope: str = "", limit: int = 20, project: str = "", deps: NavigationLookupPort) -> dict[str, Any]:
    """Bounded file/symbol index scan, kept outside the query facade."""
    from .ranking import tokenize
    config, store = deps.load_context(workspace_file); keywords = tokenize(query)
    project_scope = deps.resolve_project(workspace_file, project); effective = str(project_scope.get("project", "") or "")
    files: list[dict[str, Any]] = []; symbols: list[dict[str, Any]] = []; shard_used = False
    if effective:
        try:
            from ..indexing.control_plane import index_control_status
            from ..indexing.shards import load_service_shard
            generation = str(index_control_status(store).get("active_generation", "") or "")
            shard = load_service_shard(store, generation, effective) if generation else None
            if shard:
                files, symbols, shard_used = list(shard.get("files", []) or []), list(shard.get("symbols", []) or []), True
        except Exception: pass
    unavailable = bool(effective and not shard_used)
    if not shard_used and not unavailable:
        files, symbols = store.read_json_prefer_backend("file-index.json", []), store.read_json_prefer_backend("java-symbol-index.json", [])
    by_file: dict[str, list[dict[str, Any]]] = {}
    for symbol in symbols: by_file.setdefault(symbol.get("file", ""), []).append(symbol)
    hits = []
    for item in files:
        path = str(item.get("path", "")); item_project = str(item.get("project", ""))
        if (scope and scope.lower() not in path.lower()) or (effective and not deps.project_matches(effective, item_project)): continue
        entries = by_file.get(path, []); text = f"{path} {item_project} {item.get('service_name', '')}".lower(); symbols_text = deps.symbol_search_text(entries).lower()
        score = sum(token in text or token in symbols_text for token in keywords)
        if score: hits.append({"project": item_project, "service_name": item.get("service_name", ""), "path": path, "score": score, "symbol_count": sum(int(entry.get("class_count", 0))+int(entry.get("method_count", 0))+int(entry.get("field_count", 0)) for entry in entries), "suffix": item.get("suffix", "")})
    hits.sort(key=lambda row: (-int(row["score"]), -int(row["symbol_count"]), row["path"]))
    result = {"workspace": config.workspace, "query": query, "scope": scope, "project_scope": {"requested": project, "effective": effective, "source": project_scope.get("source", "none")}, "hits": hits[:limit], "total_hits": len(hits), "index_source": "service_shard" if shard_used else "service_shard_unavailable" if unavailable else "global_graph", "index_scope_unavailable": unavailable, "progressive": build_search_progressive(query, scope, hits[:limit]), "tips": ["命中后可继续调用 memory_symbol / memory_context 深挖。", "改动前建议调用 memory_impact 和 workspace_check_rules。"]}
    from memory_center.core.knowledge.state import attach_knowledge_state
    return attach_knowledge_state(store, result, query=query, project=effective, mode="memory_search_code")
