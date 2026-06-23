from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

_MIN_LEARNED_WEIGHT = 0.35
_MAX_LEARNED_WEIGHT = 0.75
_MAX_CANDIDATE_LIMIT = 48
_MAX_EVIDENCE_BUDGET = 12


@dataclass(frozen=True)
class RetrievalPolicy:
    sources: tuple[str, ...]
    graph_depth: int
    candidate_limit: int
    semantic_enabled: bool
    vector_enabled: bool
    evidence_budget: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "sources": list(self.sources),
            "graph_depth": self.graph_depth,
            "candidate_limit": self.candidate_limit,
            "semantic_enabled": self.semantic_enabled,
            "vector_enabled": self.vector_enabled,
            "evidence_budget": self.evidence_budget,
        }


def select_retrieval_policy(
    intent: Mapping[str, Any],
    freshness: Mapping[str, Any],
    learned_weights: Mapping[str, Any],
) -> RetrievalPolicy:
    """Select a deterministic retrieval plan without reading global state."""
    intent_data = dict(intent or {})
    freshness_data = dict(freshness or {})
    weights = _bounded_weights(learned_weights)

    primary = str(intent_data.get("primary_intent", "general") or "general").lower()
    full_chain = bool(intent_data.get("is_full_chain")) or primary == "walkthrough"
    chain_query = full_chain or bool(intent_data.get("is_chain_query")) or primary == "chain"
    structured = primary in {
        "class",
        "method",
        "feign",
        "mq",
        "endpoint",
        "config",
    }

    if full_chain:
        hard_sources = ["exact", "graph"]
        optional_sources = ["sparse"]
        graph_depth = 4
        candidate_limit = 24
        evidence_budget = 8
    elif chain_query:
        hard_sources = ["exact", "graph"]
        optional_sources = ["bm25", "sparse", "semantic"]
        graph_depth = 4
        candidate_limit = 28
        evidence_budget = 8
    elif structured:
        hard_sources = ["exact", "graph"]
        optional_sources = ["bm25", "sparse", "semantic", "vector"]
        graph_depth = 3 if intent_data.get("is_cross_service") else 2
        candidate_limit = 20
        evidence_budget = 6
    else:
        hard_sources = ["exact", "graph"]
        optional_sources = ["bm25", "sparse", "semantic", "vector"]
        graph_depth = 2
        candidate_limit = 28
        evidence_budget = 8

    optional_sources = _rank_optional_sources(optional_sources, weights, learned_weights)
    status = str(freshness_data.get("status", "unknown") or "unknown").lower()
    if status == "pending":
        candidate_limit += 4
        evidence_budget += 1
    elif status == "stale":
        candidate_limit += 8
        evidence_budget += 2

    if weights:
        average = sum(weights.values()) / len(weights)
        if average < 0.45:
            candidate_limit = max(12, int(candidate_limit * 0.8))
            evidence_budget = max(4, evidence_budget - 1)
        elif average > 0.65:
            candidate_limit = int(candidate_limit * 1.1)
            evidence_budget += 1

    sources = tuple(dict.fromkeys([*hard_sources, *optional_sources]))
    return RetrievalPolicy(
        sources=sources,
        graph_depth=max(1, min(6, graph_depth)),
        candidate_limit=max(8, min(_MAX_CANDIDATE_LIMIT, candidate_limit)),
        semantic_enabled="semantic" in sources,
        vector_enabled="vector" in sources,
        evidence_budget=max(1, min(_MAX_EVIDENCE_BUDGET, evidence_budget)),
    )


def _bounded_weights(raw: Mapping[str, Any]) -> dict[str, float]:
    bounded: dict[str, float] = {}
    for source, value in dict(raw or {}).items():
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        bounded[str(source)] = max(_MIN_LEARNED_WEIGHT, min(_MAX_LEARNED_WEIGHT, numeric))
    return bounded


def _rank_optional_sources(
    sources: list[str],
    weights: Mapping[str, float],
    raw_weights: Mapping[str, Any],
) -> list[str]:
    original_rank = {source: index for index, source in enumerate(sources)}
    enabled = [
        source
        for source in sources
        if source not in raw_weights or weights.get(source, 0.5) > _MIN_LEARNED_WEIGHT
    ]
    return sorted(
        enabled,
        key=lambda source: (-weights.get(source, 0.5), original_rank[source]),
    )
