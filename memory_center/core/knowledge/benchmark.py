"""Explicit performance gate for the ontology sidecar hot-path contribution."""
from __future__ import annotations

from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Any

from memory_center.core.storage.graph import GraphStore
from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.core.workspace.config import load_workspace_config


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


def evaluate_assertion_scope_gate(
    workspace_file: str,
    *,
    paths: list[str],
    apply: bool = False,
    max_scope_edges: int = 200_000,
) -> dict[str, Any]:
    """Validate that a partial scope selects less than the full assertion graph.

    ``apply`` is deliberately opt-in because it publishes a real partial index
    generation. The default read-only check is suitable for production workspaces.
    """
    store = WorkspaceStore(workspace_file)
    normalized_paths = sorted({str(path).replace("\\", "/").lstrip("/") for path in paths if path})[:48]
    if not normalized_paths:
        raise ValueError("at least one path is required")
    with GraphStore(store.graph_db_path) as graph:
        total_edges = int(graph.counts().get("edges", 0))
        selected_edges = 0
        for _ in graph.iter_assertion_rows(paths=normalized_paths):
            selected_edges += 1
            if selected_edges > max_scope_edges:
                break
    result: dict[str, Any] = {
        "schema_version": 1,
        "operation": "assertion_scope_gate",
        "paths": normalized_paths,
        "total_graph_edges": total_edges,
        "selected_assertion_edges": selected_edges,
        "scope_ratio": round(selected_edges / total_edges, 6) if total_edges else 0.0,
        "max_scope_edges": max_scope_edges,
        "read_only": not apply,
        "passed": selected_edges <= max_scope_edges and (total_edges == 0 or selected_edges < total_edges),
    }
    if apply:
        from memory_center.core.indexing.reindex import reindex_workspace
        from memory_center.core.workspace.config import load_workspace_config

        started = perf_counter()
        reindex_workspace(load_workspace_config(workspace_file), store, paths=normalized_paths)
        elapsed_ms = (perf_counter() - started) * 1000
        assertion_index = store.read_json_prefer_backend("assertion-index.json", {}) or {}
        result["apply"] = {
            "elapsed_ms": round(elapsed_ms, 3),
            "generation": assertion_index.get("generation", ""),
            "written_assertions": int(assertion_index.get("written", 0) or 0),
            "mode": assertion_index.get("mode", ""),
        }
        result["passed"] = bool(result["passed"]) and result["apply"]["written_assertions"] <= selected_edges
    return result


def evaluate_assertion_reindex_gate(
    workspace_file: str,
    *,
    paths: list[str] | None = None,
    full: bool = False,
    max_overhead_pct: float | None = None,
) -> dict[str, Any]:
    """Compare graph-only and sidecar reindex in isolated temporary stores."""
    if full is False and not paths:
        raise ValueError("paths are required unless full=True")
    config = load_workspace_config(workspace_file)
    scope = [str(path).replace("\\", "/").lstrip("/") for path in paths or [] if path][:48]
    budget = float(max_overhead_pct if max_overhead_pct is not None else (10.0 if full else 5.0))
    with TemporaryDirectory(prefix="memory-center-ontology-gate-") as root:
        baseline_store = WorkspaceStore(f"{root}/baseline/workspace.yaml")
        sidecar_store = WorkspaceStore(f"{root}/sidecar/workspace.yaml")
        from memory_center.core.indexing.reindex import reindex_workspace

        started = perf_counter()
        reindex_workspace(config, baseline_store, paths=None if full else scope, parallel=False, materialize_assertions=False)
        baseline_ms = (perf_counter() - started) * 1000
        started = perf_counter()
        reindex_workspace(config, sidecar_store, paths=None if full else scope, parallel=False, materialize_assertions=True)
        sidecar_ms = (perf_counter() - started) * 1000
        written = int((sidecar_store.read_json_prefer_backend("assertion-index.json", {}) or {}).get("written", 0) or 0)
    overhead = ((sidecar_ms - baseline_ms) / baseline_ms * 100.0) if baseline_ms > 0 else 0.0
    return {
        "schema_version": 1,
        "operation": "assertion_reindex_gate",
        "mode": "full" if full else "partial",
        "paths": scope,
        "baseline_ms": round(baseline_ms, 3),
        "sidecar_ms": round(sidecar_ms, 3),
        "overhead_pct": round(overhead, 3),
        "budget_pct": budget,
        "written_assertions": written,
        "isolated": True,
        "passed": overhead <= budget,
    }
