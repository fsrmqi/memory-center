"""Explicit offline architecture community and centrality analysis."""
from __future__ import annotations

from pathlib import Path
from time import time
from typing import Any

from memory_center.core.storage.runtime import RuntimeStore
from memory_center.core.storage.workspace import WorkspaceStore

ARCHITECTURE_COMMUNITIES_FILE = "architecture-communities.json"


def analyze_architecture_communities(workspace_file: str | Path, *, limit: int = 20) -> dict[str, Any]:
    """Compute project communities from bounded SQL aggregates and cache summary."""
    store = WorkspaceStore(workspace_file)
    bounded_limit = min(max(1, limit), 50)
    with RuntimeStore(store.graph_db_path) as graph:
        projection = graph.community_projection(limit=bounded_limit)
    relationships = projection["relationships"]
    projects = sorted({row["source_project"] for row in relationships} | {row["target_project"] for row in relationships})
    communities = _connected_components(projects, relationships)
    result = {
        "schema_version": 1,
        "kind": "architecture_communities",
        "generated_at": time(),
        "mode": "explicit_offline_aggregate",
        "limits": {"project_relationships": bounded_limit * 4, "central_nodes": bounded_limit},
        "communities": communities,
        "cross_project_relationships": relationships,
        "central_nodes": projection["central_nodes"],
        "evidence_boundary": "只聚合 SQLite 图中的跨项目边与节点度数；不读取源码、不加载完整图、不影响查询热路径。",
    }
    store.write_json(ARCHITECTURE_COMMUNITIES_FILE, result)
    return result


def architecture_communities_status(workspace_file: str | Path) -> dict[str, Any]:
    """Read only a prior explicit analysis for Workbench/status rendering."""
    return WorkspaceStore(workspace_file).read_json_prefer_backend(ARCHITECTURE_COMMUNITIES_FILE, {}) or {}


def _connected_components(projects: list[str], relationships: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parent = {project: project for project in projects}

    def find(item: str) -> str:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    for row in relationships:
        left, right = row["source_project"], row["target_project"]
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root
    grouped: dict[str, list[str]] = {}
    for project in projects:
        grouped.setdefault(find(project), []).append(project)
    return [
        {"community_id": f"community-{index + 1}", "projects": sorted(members), "project_count": len(members), "evidence_level": "INFERRED"}
        for index, members in enumerate(sorted(grouped.values(), key=lambda values: (-len(values), values)))
    ]
