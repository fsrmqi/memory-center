"""Symbol resolution and project disambiguation, separated from query facade."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from .lookup_shared import SymbolLookupPort


def resolve_symbol(workspace_file: str | Path, name: str, *, limit: int = 10, project: str = "", view: str = "full", budget: str = "medium", deps: SymbolLookupPort) -> dict[str, Any]:
    from memory_center.core.storage.runtime import RuntimeStore
    inferred = project or deps.infer_active_project(workspace_file)
    if not inferred and "." in name and not name.startswith("."):
        inferred = infer_project_from_fqn(name, workspace_file)
    internal_limit = max(limit, min(max(limit * 3, 12), 50))
    types = ["Class", "Method", "Field", "FeignClient", "FeignMethod", "Endpoint", "MQTopic", "MQConsumer", "ConfigKey", "File"]
    lookup = deps.hybrid_query(workspace_file, name, limit=internal_limit, node_types=types, project=inferred)
    all_matches = list(lookup.get("matches", []) or [])
    if inferred:
        global_lookup = deps.hybrid_query(workspace_file, name, limit=internal_limit, node_types=types, project="")
        all_matches = list(global_lookup.get("matches", []) or all_matches)
        if not lookup.get("matches"): lookup = global_lookup
    matches = [item.get("node", {}) for item in lookup.get("matches", []) if item.get("node")]
    if inferred and not any(deps.project_matches(inferred, item.get("project", "")) for item in matches):
        store = deps.load_context(workspace_file)[1]
        with RuntimeStore(store.graph_db_path) as graph:
            direct = graph.find_nodes(name.replace("#", ".").split(".")[-1], types=["Class"], limit=50)
            for node in [node for node in direct if deps.project_matches(inferred, node.get("project", ""))]:
                lookup.setdefault("matches", []).insert(0, {"node": node, "score": 999.0, "sources": ["direct_lookup"]})
        matches = [item.get("node", {}) for item in lookup.get("matches", []) if item.get("node")]
    if not matches: return {"name": name, "found": False, "matches": [], "lookup": deps.build_lookup_payload(lookup)}
    if inferred:
        scoped = [item for item in lookup.get("matches", []) if deps.project_matches(inferred, (item.get("node") or {}).get("project", ""))]
        if scoped: lookup["matches"] = scoped
    lookup["matches"] = deps.dedupe_symbols(deps.rerank_symbols(lookup.get("matches", []), name))
    matches = [item.get("node", {}) for item in lookup["matches"] if item.get("node")]
    best = deps.best_match(matches, name); fallback = deps.fallback_symbol(all_matches, name)
    if fallback and best.get("type") == "Field": best = fallback
    projects: dict[str, int] = {}
    for item in matches: projects[item.get("project") or ""] = projects.get(item.get("project") or "", 0) + 1
    filtered = lookup["matches"][:limit]; evidence = deps.project_evidence(filtered, best, inferred, limit=5)
    result: dict[str, Any] = {"name": name, "found": True, "best_match": best, "matches": filtered, "lookup": deps.augmented_lookup(lookup, anchor_node=best, project_evidence=evidence)}
    if len(projects) > 1: result["disambiguation"] = {"projects": projects, "hint": "多个模块包含同名符号，用 project 参数或 FQN 消歧"}
    if deps.is_compact(view):
        compact = deps.compact_symbol(result, budget=budget); gain = deps.measure_compact(result, compact)
        from memory_center.core.observability.tracking import log_token_gain
        log_token_gain(workspace_file, "memory_symbol", budget=budget, model="", raw_tokens=gain["raw_tokens"], compact_tokens=gain["compact_tokens"], view=view)
        return compact
    return result


def infer_project_from_fqn(fqn: str, workspace_file: str | Path) -> str:
    from .shared import load_context
    parts = fqn.replace("#", ".").split("."); segments = [part for part in parts[:-1] if part and part[0].islower()]
    stop = {"cn", "com", "org", "net", "io", "app", "api", "biz", "service", "impl", "common", "core", "dto", "vo", "entity", "config", "util", "utils", "controller", "mapper", "dao", "repository", "model", "bean", "factory", "handler", "listener", "filter", "interceptor", "aspect", "annotation", "web", "rest", "rpc", "client", "server", "base", "lib", "sdk", "starter", "autoconfigure", "properties", "website", "safe", "back", "front", "admin", "manager", "task", "job", "schedule", "message", "mq", "cache", "data", "storage"}
    config, _ = load_context(workspace_file); best = ""; score = 0
    for segment in reversed(segments):
        if len(segment) < 3 or segment in stop: continue
        candidates = []
        for project in getattr(config, "services", []) or []:
            name = str(project.name); parts = name.lower().replace("-", "_").split("_")
            value = 100 if segment == name.lower() else 80 if segment in parts else 70 if any("".join(parts[i:j]) == segment for i in range(len(parts)) for j in range(i + 2, min(i + 5, len(parts)+1))) else 50 if segment in name.lower() else 0
            if value: candidates.append((name, value))
        for name, value in candidates:
            if len(candidates) == 1: value += 20
            if value > score: best, score = name, value
        if score >= 90: break
    return best
