"""Shared request planning and latency observability for public facades."""
from __future__ import annotations

import os
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .index_control import index_control_status
from .store import WorkspaceStore

PERFORMANCE_LEDGER_FILE = "query-performance.jsonl"


@dataclass(frozen=True)
class QueryPlan:
    tier: str
    limit: int
    depth: int
    deadline_ms: int
    enable_vector: bool
    generation: str
    shard_scope: str


class QueryPlanner:
    """Plan bounded retrieval consistently across MCP, CLI, and HTTP callers."""

    def __init__(self, workspace_file: str | Path):
        self.workspace_file = str(workspace_file)
        self.store = WorkspaceStore(workspace_file)

    def plan(self, *, tier: str, limit: int, depth: int = 2, enable_vector: bool = False, project: str = "") -> QueryPlan:
        normalized = tier if tier in {"fast", "standard", "deep"} else "standard"
        caps = {
            "fast": {"limit": 8, "depth": 1, "deadline_ms": 1_500, "vector": False},
            "standard": {"limit": 20, "depth": 3, "deadline_ms": 5_000, "vector": enable_vector},
            "deep": {"limit": 50, "depth": 6, "deadline_ms": 20_000, "vector": enable_vector},
        }[normalized]
        control = index_control_status(self.store)
        return QueryPlan(
            tier=normalized,
            limit=min(max(1, limit), caps["limit"]),
            depth=min(max(1, depth), caps["depth"]),
            deadline_ms=caps["deadline_ms"],
            enable_vector=bool(caps["vector"]),
            generation=str(control.get("active_generation", "") or "legacy"),
            shard_scope=f"service:{project}" if project else "routed",
        )

    def record(self, operation: str, plan: QueryPlan, started_at: float, *, outcome: str, stages: dict[str, float] | None = None) -> dict[str, Any]:
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
        entry = {
            "operation": operation,
            "tier": plan.tier,
            "generation": plan.generation,
            "shard_scope": plan.shard_scope,
            "elapsed_ms": elapsed_ms,
            "deadline_ms": plan.deadline_ms,
            "outcome": outcome,
            "stages_ms": stages or {},
        }
        # Keep observability off the critical path for normal fast requests;
        # slow calls are always retained and the rest is sampled by default.
        sample_rate = min(1.0, max(0.0, float(os.getenv("MEMORY_CENTER_QUERY_LEDGER_SAMPLE_RATE", "0.10"))))
        if elapsed_ms >= 100 or random.random() < sample_rate:
            self.store.append_jsonl(PERFORMANCE_LEDGER_FILE, entry)
        return {**asdict(plan), "elapsed_ms": elapsed_ms, "outcome": outcome, "stages_ms": stages or {}}


def workspace_performance_summary(workspace_file: str | Path, limit: int = 200) -> dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    rows = store.read_jsonl_prefer_backend(PERFORMANCE_LEDGER_FILE, limit=limit)
    if not rows:
        return {"samples": 0, "p50_ms": 0.0, "p95_ms": 0.0, "timeouts": 0}
    values = sorted(float(row.get("elapsed_ms", 0) or 0) for row in rows)
    def percentile(ratio: float) -> float:
        return round(values[min(len(values) - 1, int((len(values) - 1) * ratio))], 2)
    return {"samples": len(values), "p50_ms": percentile(0.50), "p95_ms": percentile(0.95), "p99_ms": percentile(0.99), "timeouts": sum(1 for row in rows if row.get("outcome") == "deadline_exceeded")}
