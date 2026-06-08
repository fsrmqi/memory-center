"""Unified Explanation Schema — structured explanations for agents and users.

Implements UA-2 from NEXT_PHASE_MASTER_PLAN.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Explanation:
    """Structured explanation for a query result, impact analysis, or chain trace."""
    subject: str
    summary: str
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    semantic_strength: str = "inferred"  # fact | inferred | derived
    confidence: float = 0.5
    persona: str = "developer"  # developer | architect | manager
    next_actions: List[str] = field(default_factory=list)
    related_entities: List[Dict[str, Any]] = field(default_factory=list)

    def to_compact(self) -> Dict[str, Any]:
        """Compact view for token-constrained contexts."""
        return {
            "subject": self.subject,
            "summary": self.summary,
            "strength": self.semantic_strength,
            "confidence": round(self.confidence, 2),
            "next_actions": self.next_actions[:3],
        }

    def to_full(self) -> Dict[str, Any]:
        """Full view with all evidence."""
        return {
            "subject": self.subject,
            "summary": self.summary,
            "evidence": self.evidence,
            "semantic_strength": self.semantic_strength,
            "confidence": round(self.confidence, 4),
            "persona": self.persona,
            "next_actions": self.next_actions,
            "related_entities": self.related_entities,
        }

    def adapt_for_persona(self, persona: str) -> "Explanation":
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
    evidence: "list[dict]" | None = None,
    semantic_strength: str = "inferred",
    confidence: float = 0.5,
    next_actions: "list[str]" | None = None,
) -> dict:
    """Build a standard explanation dict (D-03 helper)."""
    valid = {"fact", "inferred", "derived"}
    return {
        "subject": subject,
        "summary": summary,
        "evidence": evidence or [],
        "semantic_strength": semantic_strength if semantic_strength in valid else "inferred",
        "confidence": max(0.0, min(1.0, confidence)),
        "next_actions": next_actions or [],
    }


def merge_explanations(explanations: "list[dict]") -> dict:
    """Merge multiple explanation entries into a combined view."""
    if not explanations:
        return explanation_entry(summary="No explanations available", confidence=0.0)
    summaries = [e.get("summary", "") for e in explanations if e.get("summary")]
    all_evidence = []
    all_refs = []
    for e in explanations:
        all_evidence.extend(e.get("evidence", []))
        all_refs.extend(e.get("next_actions", []))
    strength_order = {"fact": 2, "inferred": 1, "derived": 0}
    weakest = min((strength_order.get(e.get("semantic_strength", "inferred"), 1) for e in explanations), default=0)
    strength_map = {2: "fact", 1: "inferred", 0: "derived"}
    min_conf = min((e.get("confidence", 0.5) for e in explanations), default=0.5)
    return {
        "summary": " | ".join(summaries[:5]),
        "evidence": all_evidence[:20],
        "semantic_strength": strength_map.get(weakest, "inferred"),
        "confidence": round(min_conf, 3),
        "next_actions": all_refs[:10],
    }


def backward_compat_wrapper(old_explanation: dict) -> dict:
    """Convert legacy explanation dict to new schema while preserving old fields."""
    if "summary" in old_explanation and "semantic_strength" in old_explanation:
        return old_explanation
    return {
        **old_explanation,
        "summary": old_explanation.get("summary", str(old_explanation)),
        "evidence": [],
        "semantic_strength": "inferred",
        "confidence": 0.5,
        "next_actions": [],
    }
