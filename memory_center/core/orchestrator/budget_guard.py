"""Bounded invocation contracts shared by graph-aware agent workflows."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class InvocationBudget:
    max_stages: int = 8
    max_output_tokens: int = 2400
    max_elapsed_ms: float = 10_000.0
    started: float = field(default_factory=time.perf_counter)
    stages: list[str] = field(default_factory=list)
    stopped_reason: str = ""

    def enter(self, stage: str) -> bool:
        if self.stopped_reason:
            return False
        if len(self.stages) >= self.max_stages:
            self.stopped_reason = "stage_budget_exhausted"
            return False
        if self.elapsed_ms() >= self.max_elapsed_ms:
            self.stopped_reason = "elapsed_budget_exhausted"
            return False
        self.stages.append(stage)
        return True

    def elapsed_ms(self) -> float:
        return round((time.perf_counter() - self.started) * 1000, 3)

    def contract(self, *, fingerprint: str, detail_level: str) -> dict[str, Any]:
        elapsed_ms = self.elapsed_ms()
        return {
            "schema_version": 1,
            "fingerprint": fingerprint,
            "detail_level": detail_level,
            "stages_used": list(self.stages),
            "stage_count": len(self.stages),
            "max_stages": self.max_stages,
            "max_output_tokens": self.max_output_tokens,
            "max_elapsed_ms": self.max_elapsed_ms,
            "elapsed_ms": elapsed_ms,
            "elapsed_budget_exceeded": elapsed_ms >= self.max_elapsed_ms,
            "stopped": bool(self.stopped_reason),
            "stop_reason": self.stopped_reason,
            "escalation_order": ["minimal", "standard", "deep"],
            "stop_conditions": [
                "evidence_complete",
                "stage_budget_exhausted",
                "elapsed_budget_exhausted",
                "refresh_scope_truncated",
                "user_confirmation_required",
            ],
        }


def invocation_fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8", errors="replace")).hexdigest()[:24]
