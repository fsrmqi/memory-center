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
SCOPED_REFRESH_PERFORMANCE_FILE = "scoped-refresh-performance.jsonl"
DEFAULT_SCOPED_REFRESH_BUDGET_MS = 10_000.0

# Per-bucket refresh budgets (refresh-budget tiering). Buckets are derived
# from the changed scope, so we never compare a single low-risk file against
# a multi-service contract refresh with one global P95.
BUCKET_BUDGETS_MS: dict[str, float] = {
    "plain_java/single_file": 8_000.0,
    "plain_java/multi_file_single_service": 15_000.0,
    "plain_java/multi_service": 30_000.0,
    "contract/single_file": 15_000.0,
    "contract/multi_file_single_service": 30_000.0,
    "contract/multi_service": 60_000.0,
    "delete_or_move/single_file": 8_000.0,
    "delete_or_move/multi_file": 20_000.0,
    "unknown/single_file": 8_000.0,
    "unknown/multi_file_single_service": 15_000.0,
    "unknown/multi_service": 30_000.0,
}
DEFAULT_BUCKET_BUDGET_MS = 15_000.0

# Contract-ish file fragments used to classify a changed path's risk.
_CONTRACT_HINTS = (
    "controller", "feign", "dto", "mq", "producer", "consumer", "config",
    "topic", "endpoint", "api",
)


def classify_refresh_bucket(
    *,
    paths: list[str] | None = None,
    projects: list[str] | None = None,
    scanned_files: int = 0,
) -> str:
    """Classify a scoped refresh into a bucket: category/scope.

    category: plain_java | contract | delete_or_move | unknown
    scope: single_file | multi_file_single_service | multi_file | multi_service
    """
    path_list = [str(p) for p in (paths or []) if str(p).strip()]
    proj_list = [str(p) for p in (projects or []) if str(p).strip()]
    lower_paths = " ".join(p.lower() for p in path_list)

    if any(token in lower_paths for token in ("delete", "moved", "renamed")) or scanned_files == 0:
        category = "delete_or_move"
    elif any(hint in lower_paths for hint in _CONTRACT_HINTS):
        category = "contract"
    else:
        category = "plain_java"

    n = max(1, int(scanned_files) or len(path_list) or 1)
    if len(proj_list) > 1:
        scope = "multi_service"
    elif n == 1:
        scope = "single_file"
    elif len(proj_list) == 1:
        scope = "multi_file_single_service"
    else:
        scope = "multi_file"

    key = f"{category}/{scope}"
    return key if key in BUCKET_BUDGETS_MS else f"{category}/multi_file"


def bucket_budget_ms(bucket: str) -> float:
    return BUCKET_BUDGETS_MS.get(bucket, DEFAULT_BUCKET_BUDGET_MS)


def record_scoped_refresh_performance(
    workspace_file: str | Path,
    *,
    timing_ms: dict[str, float],
    path_count: int,
    project_count: int,
    scanned_files: int,
    generation: str,
    paths: list[str] | None = None,
    projects: list[str] | None = None,
) -> dict[str, Any]:
    """Persist one aggregate-only scoped-refresh observation, bucketed.

    Buckets (category/scope) get their own budget so a single low-risk file is
    never compared against a multi-service contract refresh with one global
    P95.
    """
    store = WorkspaceStore(workspace_file)
    normalized_timings = {
        str(key): round(max(0.0, float(value or 0)), 2)
        for key, value in timing_ms.items()
        if key
    }
    total_ms = float(normalized_timings.get("total", 0.0) or 0.0)
    stage_timings = {
        key: value
        for key, value in normalized_timings.items()
        if key not in {"total", "pipeline_total"}
    }
    dominant_stage = max(stage_timings, key=stage_timings.get) if stage_timings else "unknown"
    bucket = classify_refresh_bucket(
        paths=paths or [],
        projects=projects or [],
        scanned_files=int(scanned_files or 0),
    )
    budget_ms = bucket_budget_ms(bucket)
    observation = {
        "schema_version": 1,
        "recorded_at": time.time(),
        "generation": generation,
        "bucket": bucket,
        "scope": {
            "path_count": max(0, int(path_count)),
            "project_count": max(0, int(project_count)),
            "scanned_files": max(0, int(scanned_files)),
        },
        "timing_ms": normalized_timings,
        "dominant_stage": dominant_stage,
        "budget_ms": budget_ms,
        "status": "healthy" if total_ms <= budget_ms else "warning",
    }
    store.append_jsonl(SCOPED_REFRESH_PERFORMANCE_FILE, observation)
    return {
        "status": observation["status"],
        "total_ms": total_ms,
        "budget_ms": budget_ms,
        "bucket": bucket,
        "dominant_stage": dominant_stage,
        "next_action": _scoped_refresh_next_action(observation),
    }


def scoped_refresh_performance_status(workspace_file: str | Path, limit: int = 20) -> dict[str, Any]:
    """Read a bounded scoped-refresh trend without source/path disclosure."""
    store = WorkspaceStore(workspace_file)
    rows = store.read_jsonl(
        SCOPED_REFRESH_PERFORMANCE_FILE,
        limit=min(100, max(1, int(limit))),
    )
    if not rows:
        return {
            "samples": 0,
            "status": "baseline_missing",
            "p50_ms": 0.0,
            "p95_ms": 0.0,
            "next_action": "执行一次显式局部刷新以建立性能基线。",
            "recent": [],
        }
    totals = [float((row.get("timing_ms") or {}).get("total", 0) or 0) for row in rows]
    latest = rows[-1]
    budget_ms = float(latest.get("budget_ms", DEFAULT_SCOPED_REFRESH_BUDGET_MS) or DEFAULT_SCOPED_REFRESH_BUDGET_MS)
    p95_ms = percentile(totals, 0.95)
    status = "healthy" if p95_ms <= budget_ms and latest.get("status") == "healthy" else "warning"

    # Per-bucket tiering: aggregate P50/P95/dominant/budget per bucket so a
    # single-file refresh is never judged against a multi-service budget.
    from collections import defaultdict

    buckets: dict[str, dict[str, Any]] = defaultdict(lambda: {"samples": 0, "totals": [], "dominants": []})
    for row in rows:
        bucket = str(row.get("bucket", "") or "unknown/multi_file")
        buckets[bucket]["samples"] += 1
        buckets[bucket]["totals"].append(float((row.get("timing_ms") or {}).get("total", 0) or 0))
        buckets[bucket]["dominants"].append(str(row.get("dominant_stage", "unknown") or "unknown"))
    from collections import Counter

    by_bucket: dict[str, dict[str, Any]] = {}
    for bucket, data in buckets.items():
        from collections import Counter as _C

        dominant = _C(data["dominants"]).most_common(1)[0][0] if data["dominants"] else "unknown"
        # `unknown/multi_file` buckets are legacy observations recorded before
        # per-bucket classification existed (no path/project info to derive a
        # real bucket). They are not actionable; only real buckets with >=5
        # samples and P95 over their own budget trigger over_budget.
        legacy = bucket == "unknown/multi_file"
        by_bucket[bucket] = {
            "samples": data["samples"],
            "p50_ms": percentile(data["totals"], 0.50),
            "p95_ms": percentile(data["totals"], 0.95),
            "budget_ms": bucket_budget_ms(bucket),
            "dominant_stage": dominant,
            "legacy": legacy,
            "over_budget": (not legacy) and data["samples"] >= 5 and percentile(data["totals"], 0.95) > bucket_budget_ms(bucket),
        }
    # Global status: healthy only if every real bucket with >=5 samples is within
    # its own budget; legacy unknown buckets and the latest row's legacy status
    # do not gate the decision (only real, actionable buckets do).
    any_bucket_over = any(b["over_budget"] for b in by_bucket.values())
    real_buckets = [b for k, b in by_bucket.items() if not b["legacy"]]
    latest_is_legacy = str(latest.get("bucket", "") or "") == "unknown/multi_file"
    status = "warning" if any_bucket_over or (not latest_is_legacy and latest.get("status") != "healthy") else "healthy"
    over_budget_buckets = sorted(
        [k for k, b in by_bucket.items() if b["over_budget"]],
    )
    return {
        "samples": len(rows),
        "status": status,
        "p50_ms": percentile(totals, 0.50),
        "p95_ms": p95_ms,
        "max_ms": round(max(totals), 2),
        "budget_ms": budget_ms,
        "by_bucket": by_bucket,
        "over_budget_buckets": over_budget_buckets,
        "latest": latest,
        "next_action": _scoped_refresh_next_action(latest),
        "recent": rows[-min(20, max(1, int(limit))) :],
    }


def _scoped_refresh_next_action(observation: dict[str, Any]) -> str:
    if observation.get("status") == "healthy":
        return "局部刷新在预算内；继续使用当前有界刷新策略。"
    stage = str(observation.get("dominant_stage", "unknown") or "unknown")
    actions = {
        "load_indexes": "优先检查大型运行时索引反序列化与事务内缓存。",
        "persist_indexes": "优先检查局部刷新是否仍在重写完整索引载荷。",
        "graph_update": "优先分析局部图替换、调用解析与 FTS 更新。",
        "retrieval_update": "优先分析 BM25、dense vector 与 ANN 的增量同步。",
        "generation_publish": "优先分析受影响服务分片的 copy-on-write 发布。",
        "assertion_projection": "优先分析稀疏断言投影，禁止复制静态图边。",
    }
    return actions.get(stage, "按 timing_ms 中耗时最高阶段继续做有界 profile。")


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
