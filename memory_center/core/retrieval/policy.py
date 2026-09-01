from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

_MIN_LEARNED_WEIGHT = 0.35
_MAX_LEARNED_WEIGHT = 0.75
_MAX_CANDIDATE_LIMIT = 48
_MAX_EVIDENCE_BUDGET = 12

# 任务类型 purpose 预算预设(设计参考 OpenViking context_assembler 的
# PURPOSE_PRESETS):按意图归并把检索预算向任务形态倾斜,而不是只按
# fast/standard/deep 深度分档。delta 施加在基线预算之上,仍受上下限约束。
# - contract_change: 契约类改动需要更多候选做影响面对照;
# - quick_fix: 单点修复收窄候选,避免上下文过宽;
# - full_chain / general: 保持基线。
PURPOSE_DELTAS: dict[str, dict[str, int]] = {
    "contract_change": {"candidate_limit": 6, "evidence_budget": 2, "graph_depth": 0},
    "quick_fix": {"candidate_limit": -6, "evidence_budget": -1, "graph_depth": 0},
    "full_chain": {"candidate_limit": 0, "evidence_budget": 0, "graph_depth": 0},
    "general": {"candidate_limit": 0, "evidence_budget": 0, "graph_depth": 0},
}

_CONTRACT_INTENTS = frozenset({"feign", "mq", "endpoint", "config"})
_PURPOSE_INTENT_MARKERS: dict[str, tuple[str, ...]] = {
    "quick_fix": ("fix", "修复", "bug", "报错", "异常", "失败", "小改", "quick"),
}


def classify_purpose(intent: Mapping[str, Any]) -> str:
    """把检索意图归并为任务 purpose(纯函数,确定性)。

    优先级:全链路 > 契约类 > 快速修复 > general。契约类与快速修复同时
    命中时按契约类处理(契约安全优先于预算收窄)。
    """
    intent_data = dict(intent or {})
    primary = str(intent_data.get("primary_intent", "general") or "general").lower()
    if bool(intent_data.get("is_full_chain")) or primary == "walkthrough":
        return "full_chain"
    if primary in _CONTRACT_INTENTS:
        return "contract_change"
    text = str(intent_data.get("query", "") or intent_data.get("intent", "") or "").lower()
    if primary in {"class", "method"} and any(marker in text for marker in _PURPOSE_INTENT_MARKERS["quick_fix"]):
        return "quick_fix"
    return "general"


@dataclass(frozen=True)
class RetrievalPolicy:
    purpose: str
    sources: tuple[str, ...]
    graph_depth: int
    candidate_limit: int
    semantic_enabled: bool
    vector_enabled: bool
    evidence_budget: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "purpose": self.purpose,
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

    # 任务 purpose 预算倾斜(additive,确定性):在基线与新鲜度调整之后施加。
    purpose = classify_purpose(intent_data)
    deltas = PURPOSE_DELTAS.get(purpose, {})
    if deltas:
        candidate_limit += int(deltas.get("candidate_limit", 0))
        evidence_budget += int(deltas.get("evidence_budget", 0))
        graph_depth += int(deltas.get("graph_depth", 0))

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
        purpose=purpose,
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
