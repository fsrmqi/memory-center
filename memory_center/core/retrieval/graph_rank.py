"""有界的查询个性化图排序。"""
from __future__ import annotations

from collections import defaultdict

from memory_center.core.storage.runtime import RuntimeStore

_RELATION_WEIGHT = {
    "CALLS": 1.0,
    "FEIGN_CALLS": 1.0,
    "IMPLEMENTS": 0.85,
    "EXPOSES": 0.8,
    "PUBLISHES": 0.75,
    "CONSUMES": 0.75,
    "USES_CONFIG": 0.65,
}


def bounded_personalized_rank(
    graph: RuntimeStore,
    seeds: list[str],
    *,
    max_depth: int = 2,
    frontier_limit: int = 96,
) -> dict[str, float]:
    """从少量查询种子做关系加权传播，绝不扫描整个图。"""
    seed_ids = [seed for seed in dict.fromkeys(seeds) if seed]
    if not seed_ids or not hasattr(graph, "edges_for_node"):
        return {}
    scores: dict[str, float] = defaultdict(float)
    frontier = {seed: 1.0 / len(seed_ids) for seed in seed_ids}
    for seed, score in frontier.items():
        scores[seed] += score
    for depth in range(1, max(1, max_depth) + 1):
        expanded: dict[str, float] = defaultdict(float)
        for node_id, node_score in sorted(frontier.items(), key=lambda item: -item[1])[:frontier_limit]:
            edges = graph.edges_for_node(node_id, direction="both", limit=frontier_limit)
            if not edges:
                continue
            normalizer = sum(_RELATION_WEIGHT.get(str(edge.get("type", "") or ""), 0.35) for edge in edges) or 1.0
            for edge in edges:
                edge_type = str(edge.get("type", "") or "")
                neighbor = str(edge.get("target_id") if edge.get("source_id") == node_id else edge.get("source_id"))
                if not neighbor:
                    continue
                transition = _RELATION_WEIGHT.get(edge_type, 0.35) / normalizer
                expanded[neighbor] += node_score * transition * (0.62 ** depth)
        frontier = dict(sorted(expanded.items(), key=lambda item: -item[1])[:frontier_limit])
        for node_id, score in frontier.items():
            scores[node_id] += score
    return dict(scores)
