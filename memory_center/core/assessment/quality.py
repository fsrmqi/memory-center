from __future__ import annotations

from collections.abc import Iterable
from typing import Any

EVIDENCE_LEVEL_EXTRACTED = "EXTRACTED"
EVIDENCE_LEVEL_INFERRED = "INFERRED"
EVIDENCE_LEVEL_AMBIGUOUS = "AMBIGUOUS"
EVIDENCE_LEVEL_VERIFIED = "VERIFIED"
EVIDENCE_LEVELS = frozenset(
    {
        EVIDENCE_LEVEL_EXTRACTED,
        EVIDENCE_LEVEL_INFERRED,
        EVIDENCE_LEVEL_AMBIGUOUS,
        EVIDENCE_LEVEL_VERIFIED,
    }
)


def evidence_level_for(item: dict[str, Any] | None = None, *, semantic_strength: str = "") -> str:
    """Return the additive public evidence level for one result.

    ``VERIFIED`` is deliberately opt-in: a high confidence score or a direct
    parse only proves that the item was extracted, not that it was validated
    against a running system, test result, or explicit human confirmation.
    """
    payload = item or {}
    explicit = str(payload.get("evidence_level", "") or "").upper()
    if explicit in EVIDENCE_LEVELS:
        return explicit
    if payload.get("verified") is True or str(payload.get("verification_status", "")).lower() in {
        "verified",
        "confirmed",
        "passed",
    }:
        return EVIDENCE_LEVEL_VERIFIED
    strength = str(
        semantic_strength
        or payload.get("semantic_strength", "")
        or payload.get("_semantic_strength", "")
        or payload.get("evidence_type", "")
    ).lower()
    if payload.get("_is_fallback") or payload.get("ambiguous") is True:
        return EVIDENCE_LEVEL_AMBIGUOUS
    if strength in {"fact", "confirmed", "extracted"}:
        return EVIDENCE_LEVEL_EXTRACTED
    if strength in {"inferred", "derived"}:
        return EVIDENCE_LEVEL_INFERRED
    return EVIDENCE_LEVEL_AMBIGUOUS


def annotate_evidence_level(item: dict[str, Any], *, semantic_strength: str = "") -> dict[str, Any]:
    """Return an additive copy of *item* with an ``evidence_level`` field."""
    result = dict(item)
    result["evidence_level"] = evidence_level_for(result, semantic_strength=semantic_strength)
    return result


def evidence_level_counts(evidence: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Count public evidence levels without rewriting legacy evidence fields."""
    counts = {level: 0 for level in sorted(EVIDENCE_LEVELS)}
    for item in evidence:
        if isinstance(item, dict):
            counts[evidence_level_for(item)] += 1
    return counts


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
    level_counts = evidence_level_counts(rows)
    confidences: list[float] = []
    for row in rows:
        counts[_evidence_type(row)] += 1
        confidence = float(row.get("confidence", row.get("score", 0.0)) or 0.0)
        confidences.append(min(1.0, max(0.0, confidence)))
    confidence = round(sum(confidences) / len(confidences), 4) if confidences else 0.0
    stale = freshness_status in {"stale", "pending", "outdated"}
    verification_required = (
        stale
        or not rows
        or level_counts[EVIDENCE_LEVEL_AMBIGUOUS] > 0
        or level_counts[EVIDENCE_LEVEL_INFERRED] > 0
        or (counts["fact"] == 0 and confidence < 0.85)
    )
    actions: list[str] = []
    if stale:
        actions.append("refresh_index")
    if verification_required:
        actions.append("verify_with_live_source")
    return {
        "evidence_counts": counts,
        "evidence_level_counts": level_counts,
        "confidence": confidence,
        "freshness_status": freshness_status or "unknown",
        "verification_required": verification_required,
        "recommended_actions": actions,
    }
