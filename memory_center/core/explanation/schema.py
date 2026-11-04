"""Unified Explanation Schema (D-03) — structured explanations for agents and users.

Implements UA-2 from NEXT_PHASE_MASTER_PLAN.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from memory_center.core.assessment.quality import evidence_level_for

# ---------------------------------------------------------------------------
# Display rules per semantic strength (D-03 spec)
# fact:      directly observed — high prominence
# inferred:  from naming/annotation/graph patterns — label clearly
# derived:   multi-hop or heuristic — always attach evidence
# ---------------------------------------------------------------------------
DISPLAY_RULES: dict[str, dict[str, Any]] = {
    "fact":      {"label": "事实", "prominence": "high", "require_evidence": False},
    "inferred":  {"label": "推断", "prominence": "medium", "require_evidence": True},
    "derived":   {"label": "派生", "prominence": "low", "require_evidence": True},
}
@dataclass
class Explanation:
    """Structured explanation for a query result, impact analysis, or chain trace."""
    subject: str
    summary: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    semantic_strength: str = "inferred"  # fact | inferred | derived
    confidence: float = 0.5
    persona: str = "developer"  # developer | architect | manager
    next_actions: list[str] = field(default_factory=list)
    related_entities: list[dict[str, Any]] = field(default_factory=list)
    next_refs: list[dict[str, str]] = field(default_factory=list)
    evidence_level: str = ""  # EXTRACTED | INFERRED | AMBIGUOUS | VERIFIED

    def to_compact(self) -> dict[str, Any]:
        """Compact view for token-constrained contexts."""
        return {
            "subject": self.subject,
            "summary": self.summary,
            "strength": self.semantic_strength,
            "evidence_level": evidence_level_for(
                {"evidence_level": self.evidence_level}, semantic_strength=self.semantic_strength
            ),
            "confidence": round(self.confidence, 2),
            "next_actions": self.next_actions[:3],
            "next_refs": self.next_refs[:3],
        }

    def to_full(self) -> dict[str, Any]:
        """Full view with all evidence."""
        return {
            "subject": self.subject,
            "summary": self.summary,
            "evidence": self.evidence,
            "semantic_strength": self.semantic_strength,
            "evidence_level": evidence_level_for(
                {"evidence_level": self.evidence_level}, semantic_strength=self.semantic_strength
            ),
            "confidence": round(self.confidence, 4),
            "persona": self.persona,
            "next_actions": self.next_actions,
            "related_entities": self.related_entities,
            "display_rule": DISPLAY_RULES.get(self.semantic_strength, DISPLAY_RULES["inferred"]),
            "next_refs": self.next_refs,
        }

    def adapt_for_persona(self, persona: str) -> Explanation:
        """Return a persona-adapted copy of this explanation."""
        import copy
        adapted = copy.deepcopy(self)
        adapted.persona = persona

        if persona == "architect":
            # Architect: focus on patterns, dependencies, risks
            adapted.summary = f"[架构视角] {self.summary}"
            adapted.next_actions = [a for a in self.next_actions if any(k in a.lower() for k in ["依赖", "架构", "风险", "重构", "pattern", "architecture"])]
        elif persona == "manager":
            # Manager: focus on impact, timeline, risk
            adapted.summary = f"[管理视角] {self.summary}"
            adapted.next_actions = [a for a in self.next_actions if any(k in a.lower() for k in ["影响", "风险", "测试", "部署", "impact", "risk"])]
        # developer: default, no changes

        return adapted


def explanation_entry(
    subject: str = "",
    summary: str = "",
    next_refs: list[dict[str, str]] | None = None,
    evidence: list[dict] | None = None,
    semantic_strength: str = "inferred",
    confidence: float = 0.5,
    next_actions: list[str] | None = None,
    evidence_level: str = "",
) -> dict:
    """Build a standard explanation dict (D-03 helper)."""
    valid = {"fact", "inferred", "derived"}
    entry: dict = {
        "subject": subject,
        "summary": summary,
        "evidence": evidence or [],
        "semantic_strength": semantic_strength if semantic_strength in valid else "inferred",
        "confidence": max(0.0, min(1.0, confidence)),
        "next_actions": next_actions or [],
        "next_refs": next_refs or [],
    }
    entry["evidence_level"] = evidence_level_for(entry, semantic_strength=semantic_strength) if not evidence_level else evidence_level_for({"evidence_level": evidence_level})
    return entry


def display_rule_for_strength(strength: str) -> dict[str, Any]:
    """Return the display rule for a given semantic strength level."""
    return DISPLAY_RULES.get(strength, DISPLAY_RULES["inferred"])


def merge_explanations(explanations: list[dict]) -> dict:
    """Merge multiple explanation entries into a combined view."""
    if not explanations:
        return explanation_entry(summary="No explanations available", confidence=0.0)
    summaries = [e.get("summary", "") for e in explanations if e.get("summary")]
    all_evidence = []
    all_actions = []
    all_refs = []
    for e in explanations:
        all_evidence.extend(e.get("evidence", []))
        all_actions.extend(e.get("next_actions", []))
        all_refs.extend(e.get("next_refs", []))
    strength_order = {"fact": 2, "inferred": 1, "derived": 0}
    weakest = min((strength_order.get(e.get("semantic_strength", "inferred"), 1) for e in explanations), default=0)
    strength_map = {2: "fact", 1: "inferred", 0: "derived"}
    level_order = {"VERIFIED": 3, "EXTRACTED": 2, "INFERRED": 1, "AMBIGUOUS": 0}
    weakest_level = min(
        (
            level_order.get(evidence_level_for(entry), level_order["AMBIGUOUS"])
            for entry in explanations
        ),
        default=level_order["AMBIGUOUS"],
    )
    level_map = {value: key for key, value in level_order.items()}
    min_conf = min((e.get("confidence", 0.5) for e in explanations), default=0.5)
    return {
        "subject": " | ".join(e.get("subject", "") for e in explanations if e.get("subject"))[:200],
        "summary": " | ".join(summaries[:5]),
        "evidence": all_evidence[:20],
        "semantic_strength": strength_map.get(weakest, "inferred"),
        "evidence_level": level_map[weakest_level],
        "confidence": round(min_conf, 3),
        "next_actions": all_actions[:10],
        "next_refs": all_refs[:10],
    }
