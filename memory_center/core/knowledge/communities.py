"""Explicit offline architecture community and centrality analysis."""
from __future__ import annotations

import hashlib
import random
from collections import defaultdict, deque
from pathlib import Path
from time import time
from typing import Any

from memory_center.core.storage.runtime import RuntimeStore
from memory_center.core.storage.workspace import WorkspaceStore

ARCHITECTURE_COMMUNITIES_FILE = "architecture-communities.json"
ARCHITECTURE_ALGORITHM_VERSION = "architecture_health_v2"


def analyze_architecture_communities(workspace_file: str | Path, *, limit: int = 20) -> dict[str, Any]:
    """Compute project communities from bounded SQL aggregates and cache summary."""
    store = WorkspaceStore(workspace_file)
    bounded_limit = min(max(1, limit), 50)
    with RuntimeStore(store.graph_db_path) as graph:
        projection = graph.community_projection(limit=bounded_limit)
    relationships = projection["relationships"]
    projects = sorted({row["source_project"] for row in relationships} | {row["target_project"] for row in relationships})
    communities, algorithm = _detect_weighted_communities(projects, relationships)
    project_membership = {
        project: community["community_id"]
        for community in communities
        for project in community["projects"]
    }
    bridge_projects = _project_betweenness(projects, relationships)
    anomalies = _architecture_anomalies(
        projection.get("typed_relationships", []), project_membership
    )
    untested_hotspots = [
        {
            **row,
            "evidence_level": "INFERRED",
            "reason": "High graph degree without a bounded test-edge signal.",
        }
        for row in projection["central_nodes"]
        if int(row.get("degree", 0) or 0) >= 5 and int(row.get("test_edge_count", 0) or 0) == 0
    ][:bounded_limit]
    input_hash = hashlib.sha256(
        repr(sorted((row["source_project"], row["target_project"], row["edge_count"]) for row in relationships)).encode("utf-8")
    ).hexdigest()
    result = {
        "schema_version": 2,
        "kind": "architecture_communities",
        "analysis_kind": "architecture_health",
        "generated_at": time(),
        "mode": "explicit_offline_aggregate",
        "algorithm": algorithm,
        "algorithm_version": ARCHITECTURE_ALGORITHM_VERSION,
        "random_seed": 42,
        "input_hash": input_hash,
        "limits": {"project_relationships": bounded_limit * 4, "central_nodes": bounded_limit},
        "communities": communities,
        "cross_project_relationships": relationships,
        "central_nodes": projection["central_nodes"],
        "bridge_projects": bridge_projects[:bounded_limit],
        "surprising_connections": anomalies[:bounded_limit],
        "knowledge_gaps": {"untested_hotspots": untested_hotspots},
        "evidence_level": "INFERRED",
        "evidence_boundary": "只聚合 SQLite 图中的跨项目边与节点度数；异常与社区均为待验证推断。不读取源码、不加载完整图、不影响查询热路径。",
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


def _detect_weighted_communities(
    projects: list[str], relationships: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not projects:
        return [], {"name": "none", "status": "empty"}
    try:
        import igraph as ig  # type: ignore[import-not-found]

        index = {project: position for position, project in enumerate(projects)}
        weights_by_pair: dict[tuple[int, int], float] = defaultdict(float)
        for row in relationships:
            left, right = index[row["source_project"]], index[row["target_project"]]
            if left != right:
                weights_by_pair[tuple(sorted((left, right)))] += float(row.get("edge_count", 0) or 0)
        graph = ig.Graph(n=len(projects), edges=sorted(weights_by_pair), directed=False)
        weights = [weights_by_pair[pair] for pair in sorted(weights_by_pair)]
        ig.set_random_number_generator(random.Random(42))
        partition = graph.community_leiden(
            objective_function="modularity",
            weights=weights or None,
            resolution=1.0,
            n_iterations=2,
        )
        groups = [[projects[index] for index in cluster] for cluster in partition]
        name = "leiden"
    except (ImportError, ModuleNotFoundError, AttributeError, TypeError, ValueError):
        groups = _weighted_label_propagation(projects, relationships)
        name = "deterministic_weighted_label_propagation"
    rows = [
        {
            "community_id": f"community-{position + 1}",
            "projects": sorted(members),
            "project_count": len(members),
            "evidence_level": "INFERRED",
        }
        for position, members in enumerate(sorted(groups, key=lambda values: (-len(values), values)))
    ]
    return rows, {"name": name, "status": "ready", "bounded_projection": True}


def _weighted_label_propagation(
    projects: list[str], relationships: list[dict[str, Any]]
) -> list[list[str]]:
    labels = {project: project for project in projects}
    adjacency: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in relationships:
        left, right = str(row["source_project"]), str(row["target_project"])
        weight = float(row.get("edge_count", 0) or 0)
        adjacency[left][right] += weight
        adjacency[right][left] += weight
    for _ in range(20):
        changed = False
        for project in sorted(projects):
            votes: dict[str, float] = defaultdict(float)
            for neighbor, weight in adjacency[project].items():
                votes[labels[neighbor]] += weight
            if not votes:
                continue
            best = sorted(votes.items(), key=lambda item: (-item[1], item[0]))[0][0]
            if best != labels[project]:
                labels[project] = best
                changed = True
        if not changed:
            break
    grouped: dict[str, list[str]] = defaultdict(list)
    for project in projects:
        grouped[labels[project]].append(project)
    return list(grouped.values())


def _project_betweenness(
    projects: list[str], relationships: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    adjacency: dict[str, set[str]] = {project: set() for project in projects}
    for row in relationships:
        left, right = str(row["source_project"]), str(row["target_project"])
        adjacency.setdefault(left, set()).add(right)
        adjacency.setdefault(right, set()).add(left)
    scores = {project: 0.0 for project in adjacency}
    # Brandes on the bounded project projection; project counts are small and
    # this never touches the full node graph.
    for source in sorted(adjacency):
        stack: list[str] = []
        predecessors: dict[str, list[str]] = {node: [] for node in adjacency}
        paths = {node: 0.0 for node in adjacency}
        paths[source] = 1.0
        distance = {node: -1 for node in adjacency}
        distance[source] = 0
        queue = deque([source])
        while queue:
            node = queue.popleft()
            stack.append(node)
            for neighbor in sorted(adjacency[node]):
                if distance[neighbor] < 0:
                    queue.append(neighbor)
                    distance[neighbor] = distance[node] + 1
                if distance[neighbor] == distance[node] + 1:
                    paths[neighbor] += paths[node]
                    predecessors[neighbor].append(node)
        dependency = {node: 0.0 for node in adjacency}
        while stack:
            node = stack.pop()
            for previous in predecessors[node]:
                if paths[node] > 0:
                    dependency[previous] += (paths[previous] / paths[node]) * (1.0 + dependency[node])
            if node != source:
                scores[node] += dependency[node]
    scale = max(1.0, (len(adjacency) - 1) * (len(adjacency) - 2))
    return [
        {
            "project": project,
            "betweenness": round(score / scale, 6),
            "degree": len(adjacency[project]),
            "evidence_level": "INFERRED",
        }
        for project, score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        if score > 0
    ]


def _architecture_anomalies(
    relationships: list[dict[str, Any]], membership: dict[str, str]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    weak_types = {"IMPORTS", "READS_FIELD", "USES_DATA_RESOURCE", "CONFIG_PROPAGATES"}
    for row in relationships:
        source, target = str(row["source_project"]), str(row["target_project"])
        reasons: list[str] = []
        score = 0.0
        if membership.get(source) and membership.get(source) != membership.get(target):
            score += 0.5
            reasons.append("cross_community")
        if str(row.get("edge_type", "")) in weak_types:
            score += 0.2
            reasons.append("weak_relation_crosses_project")
        if int(row.get("edge_count", 0) or 0) <= 2:
            score += 0.15
            reasons.append("rare_cross_project_relation")
        if float(row.get("average_confidence", 0.0) or 0.0) < 0.7:
            score += 0.15
            reasons.append("low_confidence")
        if score >= 0.5:
            rows.append(
                {
                    **row,
                    "surprise_score": round(score, 3),
                    "reasons": reasons,
                    "evidence_level": "INFERRED",
                    "next_action": "Verify whether this cross-project dependency is intentional.",
                }
            )
    return sorted(rows, key=lambda row: (-float(row["surprise_score"]), -int(row.get("edge_count", 0)), str(row.get("source_project", ""))))
