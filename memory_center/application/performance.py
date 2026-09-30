"""Explicit real-workspace performance sampling outside the query hot path."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from memory_center.core.indexing.control_plane import index_control_status
from memory_center.core.orchestrator.query import memory_query_hybrid
from memory_center.core.retrieval.planner import (
    WORKSPACE_PERFORMANCE_SNAPSHOTS_FILE,
    percentile,
    workspace_performance_snapshot_status,
)
from memory_center.core.storage.workspace import WorkspaceStore


def record_workspace_performance_snapshot(
    workspace_file: str | Path,
    *,
    samples: int = 5,
    tier: str = "fast",
) -> dict[str, Any]:
    """Run an explicit bounded probe and persist aggregate-only P95 metrics.

    Phase B additionally probes the bounded query templates so the
    documented +10% P95 gate has a repeatable baseline for the paths that
    replaced direct graph calls (find_symbols / trace_call_paths).
    """
    bounded_samples = min(20, max(1, int(samples)))
    normalized_tier = tier if tier in {"fast", "standard", "deep"} else "fast"
    durations: list[float] = []
    template_durations: dict[str, list[float]] = {"find_symbols": [], "trace_call_paths": []}
    outcomes = {"ok": 0, "error": 0}
    template_targets = {
        "fast": ("OrderService", "OrderController"),
        "standard": ("OrderService", "OrderController"),
        "deep": ("OrderService", "OrderController"),
    }[normalized_tier]
    for i in range(bounded_samples):
        started_at = time.perf_counter()
        try:
            memory_query_hybrid(
                str(workspace_file),
                "workspace architecture overview",
                limit=8 if normalized_tier == "fast" else 20,
            )
            outcomes["ok"] += 1
        except Exception:
            # Preserve aggregate errors without persisting inputs or source.
            outcomes["error"] += 1
        durations.append(round((time.perf_counter() - started_at) * 1000, 2))

        from memory_center.core.orchestrator.templates import find_symbols, trace_call_paths

        for template, target in zip(("find_symbols", "trace_call_paths"), template_targets):
            t0 = time.perf_counter()
            try:
                if template == "find_symbols":
                    find_symbols(str(workspace_file), target, tier=normalized_tier)
                else:
                    trace_call_paths(str(workspace_file), target, direction="callers", tier=normalized_tier, depth=2)
            except Exception:
                pass
            template_durations[template].append(round((time.perf_counter() - t0) * 1000, 2))

    store = WorkspaceStore(workspace_file)
    control = index_control_status(store)
    snapshot = {
        "schema_version": 2,
        "recorded_at": time.time(),
        "generation": str(control.get("active_generation", "") or "legacy"),
        "tier": normalized_tier,
        "samples": bounded_samples,
        "p50_ms": percentile(durations, 0.50),
        "p95_ms": percentile(durations, 0.95),
        "p99_ms": percentile(durations, 0.99),
        "max_ms": round(max(durations), 2),
        "outcomes": outcomes,
        "template_p95_ms": {
            name: percentile(series, 0.95) if series else None
            for name, series in template_durations.items()
        },
    }
    store.append_jsonl(WORKSPACE_PERFORMANCE_SNAPSHOTS_FILE, snapshot)
    return {
        "snapshot": snapshot,
        "trend": workspace_performance_snapshot_status(workspace_file, limit=20),
    }
