from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def _evidence_type(item: dict[str, Any]) -> str:
    explicit = str(item.get("evidence_type", "") or item.get("semantic_strength", "") or "").lower()
    if explicit in {"fact", "inferred", "derived"}:
        return explicit
    confidence = float(item.get("confidence", item.get("score", 0.0)) or 0.0)
    if confidence >= 0.85:
        return "fact"
    if confidence >= 0.55:
        return "inferred"
    return "derived"


def build_quality_summary(
    evidence: Iterable[dict[str, Any]],
    *,
    freshness_status: str = "unknown",
) -> dict[str, Any]:
    rows = [row for row in evidence if isinstance(row, dict)]
    counts = {"fact": 0, "inferred": 0, "derived": 0}
    confidences: list[float] = []
    for row in rows:
        counts[_evidence_type(row)] += 1
        confidence = float(row.get("confidence", row.get("score", 0.0)) or 0.0)
        confidences.append(min(1.0, max(0.0, confidence)))
    confidence = round(sum(confidences) / len(confidences), 4) if confidences else 0.0
    stale = freshness_status in {"stale", "pending", "outdated"}
    verification_required = stale or not rows or (counts["fact"] == 0 and confidence < 0.85)
    actions: list[str] = []
    if stale:
        actions.append("refresh_index")
    if verification_required:
        actions.append("verify_with_live_source")
    return {
        "evidence_counts": counts,
        "confidence": confidence,
        "freshness_status": freshness_status or "unknown",
        "verification_required": verification_required,
        "recommended_actions": actions,
    }
