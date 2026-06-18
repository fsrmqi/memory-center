from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReasoningRequest:
    target_id: str
    intent: str
    max_depth: int
    evidence_budget: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "target_id", str(self.target_id or "").strip())
        object.__setattr__(self, "intent", str(self.intent or "general").strip().lower())
        object.__setattr__(self, "max_depth", max(1, int(self.max_depth or 1)))
        object.__setattr__(self, "evidence_budget", max(1, int(self.evidence_budget or 1)))
