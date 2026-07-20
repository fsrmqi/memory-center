"""Budgeted cross-service routing and parallel evidence retrieval."""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from memory_center.core.foundation.text import base_tokenize
from memory_center.core.storage.runtime import RuntimeStore
from memory_center.core.storage.workspace import WorkspaceStore

from ..indexing.control_plane import index_control_status
from ..indexing.shards import load_contract_shard, load_service_shard, load_topology_shard, service_shard_graph_path

_TIER_LIMITS = {"fast": (2, 1), "standard": (4, 2), "deep": (8, 3)}


def route_cross_service_shards(workspace_file: str | Path, query: str, *, tier: str = "standard", project: str = "") -> dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    control = index_control_status(store)
    generation = str(control.get("active_generation", "") or "")
    if not generation:
        return {"available": False, "reason": "no_active_generation", "generation": "", "selected_projects": [], "evidence": []}
    topology = load_topology_shard(store, generation) or {}
    contracts = load_contract_shard(store, generation) or {}
    max_projects, max_depth = _TIER_LIMITS.get(tier, _TIER_LIMITS["standard"])
    services = list(topology.get("services", []) or [])
    tokens = [token.lower() for token in base_tokenize(query) if len(token) > 1][:12]
    scores: dict[str, float] = {}
    evidence: list[dict[str, Any]] = []
    service_aliases: dict[str, str] = {}
    for service in services:
        name = str(service.get("name", "") or "")
        alias = str(service.get("service_name", "") or name)
        if name:
            service_aliases[alias] = name
            text = f"{name} {alias}".lower()
            score = sum(5.0 for token in tokens if token in text)
            if score:
                scores[name] = scores.get(name, 0) + score
                evidence.append({"type": "service_name", "project": name, "score": score})
    if project:
        scores[project] = scores.get(project, 0) + 100.0
        evidence.append({"type": "explicit_project", "project": project, "score": 100.0})
    for edge in topology.get("feign_edges", []) or []:
        text = json.dumps(edge, ensure_ascii=False).lower()
        if any(token in text for token in tokens):
            source = str(edge.get("from_project", "") or "")
            target = str(edge.get("to_project", "") or service_aliases.get(str(edge.get("to_service", "") or ""), ""))
            for candidate, weight in ((source, 4.0), (target, 3.0)):
                if candidate:
                    scores[candidate] = scores.get(candidate, 0) + weight
                    evidence.append({"type": "feign", "project": candidate, "score": weight, "edge": {"client": edge.get("client", ""), "to_service": edge.get("to_service", "")}})
    for kind, rows in (("api", contracts.get("apis", [])), ("feign_contract", contracts.get("feigns", [])), ("mq", contracts.get("mq", [])), ("config", contracts.get("configs", []))):
        for row in rows or []:
            text = json.dumps(row, ensure_ascii=False).lower()
            if any(token in text for token in tokens):
                candidate = str(row.get("project", "") or "")
                if candidate:
                    scores[candidate] = scores.get(candidate, 0) + 2.0
                    evidence.append({"type": kind, "project": candidate, "score": 2.0})
    selected = [project for project, _score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:max_projects]]
    expanded = _expand_topology(selected, topology, max_depth=max_depth, max_projects=max_projects)
    return {"available": True, "generation": generation, "tier": tier, "selected_projects": expanded, "seed_projects": selected, "max_depth": max_depth, "evidence": evidence[:40], "routing_mode": "topology_contract_budgeted"}


def query_cross_service_shards(workspace_file: str | Path, query: str, route: dict[str, Any], *, limit: int = 20) -> dict[str, Any]:
    if not route.get("available"):
        return {"queried_projects": [], "matches": [], "source": "unavailable"}
    store = WorkspaceStore(workspace_file)
    generation = str(route.get("generation", "") or "")
    projects = list(route.get("selected_projects", []) or [])
    if not projects:
        return {"queried_projects": [], "matches": [], "source": "no_route"}
    per_project = max(2, min(8, limit // max(1, len(projects))))
    matches: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(len(projects), 4)) as pool:
        futures = {pool.submit(_query_one_shard, store, generation, project, query, per_project): project for project in projects}
        for future in as_completed(futures):
            try:
                matches.extend(future.result())
            except Exception:
                continue
    matches.sort(key=lambda item: (-float(item.get("score", 0)), item.get("project", ""), item.get("name", "")))
    return {"queried_projects": projects, "matches": matches[:limit], "source": "parallel_service_shards"}


def evaluate_cross_shard_replay(
    workspace_file: str | Path,
    queries: list[str],
    *,
    tier: str = "standard",
    p95_budget_ms: float = 1_500.0,
) -> dict[str, Any]:
    """Run a path-free latency/completeness gate over supplied replay intents."""
    samples: list[dict[str, Any]] = []
    for query in [item.strip() for item in queries if item.strip()][:100]:
        started = time.perf_counter()
        route = route_cross_service_shards(workspace_file, query, tier=tier)
        evidence = query_cross_service_shards(workspace_file, query, route, limit=12)
        samples.append({"elapsed_ms": round((time.perf_counter() - started) * 1000, 2), "selected_project_count": len(route.get("selected_projects", [])), "evidence_count": len(evidence.get("matches", [])), "available": bool(route.get("available"))})
    values = sorted(sample["elapsed_ms"] for sample in samples)
    p95 = values[min(len(values) - 1, int((len(values) - 1) * 0.95))] if values else 0.0
    result = {"samples": len(samples), "tier": tier, "p95_ms": p95, "p95_budget_ms": p95_budget_ms, "max_selected_projects": max((sample["selected_project_count"] for sample in samples), default=0), "evidence_coverage": round(sum(1 for sample in samples if sample["evidence_count"] > 0) / len(samples), 3) if samples else 0.0, "passed": bool(samples) and p95 <= p95_budget_ms}
    WorkspaceStore(workspace_file).append_jsonl("cross-shard-replay-gates.jsonl", result)
    return result


def _query_one_shard(store: WorkspaceStore, generation: str, project: str, query: str, limit: int) -> list[dict[str, Any]]:
    graph_path = service_shard_graph_path(store, generation, project)
    nodes = []
    if graph_path:
        with RuntimeStore(graph_path) as graph:
            nodes = graph.find_nodes(query, limit=limit)
    if nodes:
        return [{"project": project, "name": node.get("name", ""), "type": node.get("type", ""), "file_path": node.get("file_path", ""), "line": node.get("line", 0), "score": 10.0 - index, "source": "service_graph_shard"} for index, node in enumerate(nodes)]
    shard = load_service_shard(store, generation, project) or {}
    tokens = [token.lower() for token in base_tokenize(query) if len(token) > 1]
    rows = []
    for item in shard.get("files", []) or []:
        text = f"{item.get('path', '')} {item.get('service_name', '')}".lower()
        score = sum(1 for token in tokens if token in text)
        if score:
            rows.append({"project": project, "name": Path(str(item.get("path", "") or "")).name, "type": "File", "file_path": item.get("path", ""), "line": 0, "score": float(score), "source": "service_json_shard"})
    return sorted(rows, key=lambda item: -float(item["score"]))[:limit]


def _expand_topology(seeds: list[str], topology: dict[str, Any], *, max_depth: int, max_projects: int) -> list[str]:
    selected = list(seeds)
    frontier = list(seeds)
    for _ in range(max_depth):
        if not frontier or len(selected) >= max_projects:
            break
        next_frontier: list[str] = []
        for edge in topology.get("feign_edges", []) or []:
            source = str(edge.get("from_project", "") or "")
            target = str(edge.get("to_project", "") or "")
            if source in frontier and target and target not in selected:
                selected.append(target)
                next_frontier.append(target)
            if target in frontier and source and source not in selected:
                selected.append(source)
                next_frontier.append(source)
            if len(selected) >= max_projects:
                break
        frontier = next_frontier
    return selected[:max_projects]
