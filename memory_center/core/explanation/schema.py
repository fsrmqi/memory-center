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
