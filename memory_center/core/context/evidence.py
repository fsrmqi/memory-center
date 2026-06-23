"""EvidenceSelector — score and rank evidence quality for context packs.

When multiple retrieval sources (graph, sparse BM25, vector ANN) return
overlapping candidates, EvidenceSelector resolves conflicts and picks the
most trustworthy evidence based on source reliability, recency, and
confidence scores.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Source reliability weights (higher = more trustworthy)
_SOURCE_WEIGHTS: Dict[str, float] = {
    "graph_exact": 1.0,
    "graph_neighbor": 0.85,
    "fts5": 0.8,
    "bm25": 0.7,
    "vector": 0.6,
    "rule_match": 0.75,
    "derived": 0.5,
}


@dataclass
class Evidence:
    """A scored piece of evidence."""
    node_id: str
    source: str
    score: float = 0.0
    confidence: float = 0.0
    description: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "source": self.source,
            "score": round(self.score, 3),
            "confidence": round(self.confidence, 3),
            "description": self.description,
            "metadata": self.metadata,
        }


class EvidenceSelector:
    """Select and rank evidence from multiple retrieval sources.

    Combines source reliability, raw score, and optional recency into a
    unified ranking.  De-duplicates by node_id, keeping the highest-scoring
    entry per node.
    """

    def __init__(self, source_weights: Optional[Dict[str, float]] = None):
        self._weights = source_weights or _SOURCE_WEIGHTS.copy()

    def select(
        self,
        candidates: List[Dict[str, Any]],
        limit: int = 10,
        min_score: float = 0.0,
    ) -> List[Evidence]:
        """Select top evidence from a mixed list of candidates.

        Each candidate dict should have at minimum:
          - node_id: str
          - source: str (e.g. "graph_exact", "bm25", "vector")
          - score: float (raw score from that source)
        Optional: confidence, description, metadata, recency_hours
        """
        seen: Dict[str, Evidence] = {}

        for cand in candidates:
            node_id = cand.get("node_id", "")
            source = cand.get("source", "unknown")
            raw_score = float(cand.get("score", 0.0))
            confidence = float(cand.get("confidence", 0.5))
            recency_hours = float(cand.get("recency_hours", 0.0))

            weight = self._weights.get(source, 0.5)
            recency_bonus = max(0.0, 0.1 * (1.0 - min(recency_hours / 168.0, 1.0)))
            combined = raw_score * weight + recency_bonus
            combined = min(1.0, combined)

            if combined < min_score:
                continue

            ev = Evidence(
                node_id=node_id,
                source=source,
                score=combined,
                confidence=confidence,
                description=cand.get("description", ""),
                metadata=cand.get("metadata", {}),
            )

            if node_id not in seen or ev.score > seen[node_id].score:
                seen[node_id] = ev

        ranked = sorted(seen.values(), key=lambda e: -e.score)
        return ranked[:limit]

    def merge_sources(
        self,
        graph_hits: List[Dict[str, Any]],
        sparse_hits: List[Dict[str, Any]],
        vector_hits: List[Dict[str, Any]],
        limit: int = 10,
    ) -> List[Evidence]:
        """Convenience: merge three source lists and return top evidence."""
        all_candidates = []
        for h in graph_hits:
            merged = {**h, "source": h.get("source", "graph_exact")}
            all_candidates.append(merged)
        for h in sparse_hits:
            merged = {**h, "source": h.get("source", "bm25")}
            all_candidates.append(merged)
        for h in vector_hits:
            merged = {**h, "source": h.get("source", "vector")}
            all_candidates.append(merged)
        return self.select(all_candidates, limit=limit)

    def explain(self, evidence: Evidence) -> str:
        """Return a human-readable explanation of why this evidence was selected."""
        weight = self._weights.get(evidence.source, 0.5)
        return (
            f"来源={evidence.source}, 可靠度权重={weight:.2f}, "
            f"综合得分={evidence.score:.3f}, 置信度={evidence.confidence:.2f}"
        )
