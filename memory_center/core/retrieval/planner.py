"""Shared request planning and latency observability for public facades."""

from __future__ import annotations

import os
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from memory_center.core.storage.workspace import WorkspaceStore

from ..indexing.control_plane import index_control_status

PERFORMANCE_LEDGER_FILE = "query-performance.jsonl"
WORKSPACE_PERFORMANCE_SNAPSHOTS_FILE = "workspace-performance-snapshots.jsonl"


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

    def plan(
        self, *, tier: str, limit: int, depth: int = 2, enable_vector: bool = False, project: str = ""
    ) -> QueryPlan:
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

    def record(
        self,
        operation: str,
        plan: QueryPlan,
        started_at: float,
        *,
        outcome: str,
        stages: dict[str, float] | None = None,
    ) -> dict[str, Any]:
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
    return {
        "samples": len(values),
        "p50_ms": percentile(values, 0.50),
        "p95_ms": percentile(values, 0.95),
        "p99_ms": percentile(values, 0.99),
        "timeouts": sum(1 for row in rows if row.get("outcome") == "deadline_exceeded"),
    }


def workspace_performance_snapshot_status(workspace_file: str | Path, limit: int = 20) -> dict[str, Any]:
    """Return a compact P95 trend and action without scanning the workspace."""
    store = WorkspaceStore(workspace_file)
    rows = store.read_jsonl_prefer_backend(WORKSPACE_PERFORMANCE_SNAPSHOTS_FILE, limit=min(100, max(1, limit)))
    if not rows:
        return {
            "samples": 0,
            "status": "baseline_missing",
            "next_action": "运行 performance-snapshot 建立当前工作区的 P95 基线。",
            "snapshots": [],
        }
    latest = rows[-1]
    previous = rows[-2] if len(rows) > 1 else None
    latest_p95 = float(latest.get("p95_ms", 0) or 0)
    previous_p95 = float((previous or {}).get("p95_ms", 0) or 0)
    regression_pct = round(((latest_p95 - previous_p95) / previous_p95) * 100, 2) if previous_p95 > 0 else 0.0
    failed = int((latest.get("outcomes") or {}).get("error", 0) or 0)
    status = "healthy"
    next_action = "保持当前索引 generation；在重建或依赖升级后再次采样。"
    if failed:
        status = "warning"
        next_action = "检查快照期间的查询错误和索引状态，再重新采样。"
    elif latest_p95 > 2_000 or regression_pct > 20:
        status = "warning"
        next_action = "检查 query-performance 的阶段耗时，并只对相关路径执行局部刷新。"
    return {
        "samples": len(rows),
        "status": status,
        "latest": latest,
        "previous": previous,
        "p95_regression_pct": regression_pct,
        "next_action": next_action,
        "snapshots": rows[-min(20, max(1, limit)) :],
    }


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int((len(ordered) - 1) * ratio))], 2)
