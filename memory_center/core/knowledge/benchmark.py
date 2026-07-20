"""Explicit performance gate for the ontology sidecar hot-path contribution."""
from __future__ import annotations

from statistics import median
from time import perf_counter
from typing import Any

from memory_center.core.storage.workspace import WorkspaceStore


def evaluate_ontology_hot_path(workspace_file: str, *, samples: int = 20, budget_ms: float = 10.0) -> dict[str, Any]:
    """Measure only the bounded assertion-summary read used by default queries."""
    store = WorkspaceStore(workspace_file)
    timings = []
    for _ in range(min(max(3, samples), 100)):
        started = perf_counter()
        store.memory_backend().assertion_summary(limit=1)
        timings.append((perf_counter() - started) * 1000)
    ordered = sorted(timings)
    p95 = ordered[min(len(ordered) - 1, int((len(ordered) - 1) * 0.95))]
    return {
        "schema_version": 1,
        "operation": "assertion_summary_hot_path",
        "samples": len(timings),
        "p50_ms": round(float(median(timings)), 3),
        "p95_ms": round(float(p95), 3),
        "budget_ms": float(budget_ms),
        "passed": p95 <= budget_ms,
        "scope": "SQLite aggregate only; excludes graph/source/history scans",
    }
