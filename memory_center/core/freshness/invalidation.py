"""Bounded domain-aware invalidation planning for changed source files."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from memory_center.core.storage.graph import GraphStore
from memory_center.core.storage.workspace import WorkspaceStore


def build_invalidation_plan(workspace_file: str | Path, paths: list[str], limit: int = 48) -> dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    normalized = sorted({path.replace("\\", "/").lstrip("/") for path in paths if path})[:limit]
    rules: list[dict[str, Any]] = []
    impacted: set[str] = set(normalized)
    categories: set[str] = set()
    try:
        with GraphStore(store.graph_db_path) as graph:
            for path in normalized:
                neighbors = graph.file_neighbors(path, limit=12)
                impacted.update(neighbors)
                kind = _classify_path(path)
                categories.add(kind)
                rules.append({"path": path, "kind": kind, "impacted_paths": neighbors, "rule": _rule_for_kind(kind)})
    except Exception:
        for path in normalized:
            kind = _classify_path(path)
            categories.add(kind)
            rules.append({"path": path, "kind": kind, "impacted_paths": [], "rule": _rule_for_kind(kind)})
    return {"paths": normalized, "impacted_paths": sorted(impacted)[:limit], "categories": sorted(categories), "rules": rules, "mode": "bounded_dependency_invalidation"}


def _classify_path(path: str) -> str:
    lower = path.lower()
    if any(token in lower for token in ("dto", "request", "response", "vo")):
        return "dto_contract"
    if "feign" in lower or "client" in lower:
        return "feign_contract"
    if any(token in lower for token in ("consumer", "producer", "listener", "mq", "kafka", "rocket")):
        return "mq_contract"
    if lower.endswith((".yml", ".yaml", ".properties")):
        return "configuration"
    if any(token in lower for token in ("controller", "api")):
        return "http_contract"
    return "code"


def _rule_for_kind(kind: str) -> str:
    return {
        "dto_contract": "propagate_to_feign_mq_serialization",
        "feign_contract": "propagate_to_server_endpoint_and_callers",
        "mq_contract": "propagate_to_producers_consumers_and_schema",
        "configuration": "propagate_to_config_readers",
        "http_contract": "propagate_to_gateway_feign_and_callers",
    }.get(kind, "propagate_to_graph_neighbors")
