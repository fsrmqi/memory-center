from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from .schemas import with_schema

def build_finding(severity: str, code: str, message: str) -> Dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "message": message,
    }


def score_to_quality(score: int) -> str:
    if score >= 85:
        return "high"
    if score >= 60:
        return "medium"
    return "low"


@dataclass
class EvalResultBuilder:
    initial_score: int = 100
    findings: List[Dict[str, Any]] = field(default_factory=list)
    score: int = field(init=False)

    def __post_init__(self) -> None:
        self.score = self.initial_score

    def add(self, severity: str, code: str, message: str, penalty: int) -> None:
        self.findings.append(build_finding(severity, code, message))
        self.score -= penalty

    def finalize(self, **payload: Any) -> Dict[str, Any]:
        final_score = max(0, self.score)
        return with_schema(
            "eval_result",
            {
            **payload,
            "score": final_score,
            "quality": score_to_quality(final_score),
            "findings": self.findings,
            },
        )
