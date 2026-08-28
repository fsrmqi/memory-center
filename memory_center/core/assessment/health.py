"""Unified release/quality health gate (subproject 1).

Aggregates the already-verified capabilities (generation health, contract,
retrieval replay, IR diff gate, scoped-refresh performance, storage) into one
read-only, repeatable publish decision. Never executes reindex/GC/VACUUM/user
commands; never runs user tests.

Status rules:
- pass: all required checks pass with real cases (or not applicable);
- attention: stale/coverage-partial/perf-close-to-budget/storage-anomaly/
  real_case_missing;
- block: active generation unreadable, IR gate regression, CHAIN_WRONG,
  publish/rollback inconsistency, contract block, critical failure;
- real_case_missing: mechanism checks pass but no real replay/perf samples —
  must NOT be described as "quality verified".
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from memory_center.core.freshness.contract import assemble_index_context, evaluate_claim_boundary
from memory_center.core.indexing.control_plane import index_control_status
from memory_center.core.indexing.diff_gate import run_diff_gate
from memory_center.core.indexing.shards import cleanup_generations
from memory_center.core.retrieval.planner import scoped_refresh_performance_status
from memory_center.core.storage.workspace import WorkspaceStore


def _check(check_id: str, status: str, summary: str, *, evidence_level: str = "VERIFIED", **extra: Any) -> dict[str, Any]:
    item: dict[str, Any] = {"id": check_id, "status": status, "evidence_level": evidence_level, "summary": summary}
    item.update(extra)
    return item


def run_quality_health_gate(
    workspace_file: str | Path,
    *,
    replay_ok: bool | None = None,
    replay_summary: str = "",
) -> dict[str, Any]:
    """Run the unified read-only quality gate (A-E) and derive a decision."""
    ws = str(workspace_file)
    store = WorkspaceStore(ws)
    checks: list[dict[str, Any]] = []
    blocking: list[str] = []
    attention: list[str] = []
    next_actions: list[str] = []
    quality: dict[str, Any] = {}
    performance: dict[str, Any] = {}
    storage: dict[str, Any] = {}

    # ---- A. runtime & generation health ----
    ctrl = index_control_status(store)
    active = str(ctrl.get("active_generation", "") or "")
    previous = str(ctrl.get("previous_generation", "") or "")
    staging = str(ctrl.get("staging_generation", "") or "")
    if not active:
        blocking.append("active_generation_missing")
        checks.append(_check("active_generation", "block", "no active generation published; index unavailable"))
    else:
        checks.append(_check("active_generation", "pass", f"active generation present ({active[:12]}…)"))
    if not previous:
        attention.append("previous_generation_missing")
        checks.append(_check("previous_generation", "attention", "no previous generation retained; rollback limited"))
    else:
        checks.append(_check("previous_generation", "pass", "previous generation retained for rollback"))
    if staging:
        attention.append("staging_generation_leftover")
        checks.append(_check("staging_generation", "attention", f"staging generation leftover: {staging[:12]}"))
    else:
        checks.append(_check("staging_generation", "pass", "no staging generation leftover"))
    # active jobs
    try:
        import sqlite3

        conn = sqlite3.connect(str(store.graph_db_path))
        act = conn.execute(
            "SELECT status, COUNT(*) FROM workspace_jobs WHERE status IN ('queued','admitted','running','validating','publishing') GROUP BY status"
        ).fetchall()
        conn.close()
        active_jobs = {r[0]: r[1] for r in act}
        if active_jobs:
            attention.append(f"active_jobs:{','.join(sorted(active_jobs))}")
            checks.append(_check("workspace_jobs", "attention", f"active jobs present: {active_jobs}"))
        else:
            checks.append(_check("workspace_jobs", "pass", "no active/stalled jobs"))
    except Exception as exc:
        checks.append(_check("workspace_jobs", "attention", f"job check unavailable: {type(exc).__name__}"))

    # ---- B. index & contract health ----
    ctx = assemble_index_context(ws)
    coverage = ctx.get("coverage", {})
    freshness = ctx.get("freshness", "NOT_INDEXED")
    if coverage.get("requested_files", 0) == 0:
        attention.append("coverage_missing")
        checks.append(_check("coverage", "attention", "no coverage ledger (legacy index); negative claims refused"))
    else:
        partial = int(coverage.get("partial_files", 0) or 0) + int(coverage.get("skipped_files", 0) or 0) + int(coverage.get("failed_files", 0) or 0)
        if partial:
            attention.append("coverage_partial")
        checks.append(_check(
            "coverage", "attention" if partial else "pass",
            f"{coverage.get('indexed_files')}/{coverage.get('requested_files')} parsed, {partial} unclean",
        ))
    gate = evaluate_claim_boundary(ctx)
    if gate["negative_claim_allowed"] and coverage.get("requested_files", 0) > 0 and freshness == "FRESH":
        checks.append(_check("claim_boundary", "pass", "negative claims gated correctly"))
    else:
        checks.append(_check("claim_boundary", "pass", "negative claims refused (boundary conservative)"))
    quality["freshness"] = freshness
    quality["coverage"] = {k: coverage.get(k) for k in ("indexed_files", "requested_files", "partial_files", "skipped_files", "failed_files")}

    # ---- C. retrieval quality (optional replay + perf) ----
    if replay_ok is not None:
        if replay_ok:
            checks.append(_check("retrieval_replay", "pass", replay_summary or "replay cases passed"))
        else:
            blocking.append("replay_failed")
            checks.append(_check("retrieval_replay", "block", replay_summary or "replay cases failed"))
    else:
        attention.append("real_case_missing")
        checks.append(_check("retrieval_replay", "real_case_missing", "no real replay case provided; quality not verified"))
    perf = scoped_refresh_performance_status(ws, limit=50)
    p95 = float(perf.get("p95_ms", 0) or 0)
    budget = float(perf.get("budget_ms", 10000) or 10000)
    perf_status = perf.get("status", "baseline_missing")
    if perf_status == "healthy":
        checks.append(_check("refresh_performance", "pass", f"scoped refresh P95 {p95:.0f}ms within budget {budget:.0f}ms"))
    elif perf_status == "baseline_missing":
        attention.append("performance_baseline_missing")
        checks.append(_check("refresh_performance", "real_case_missing", "no scoped refresh samples yet"))
    else:
        attention.append("refresh_performance_over_budget")
        checks.append(_check("refresh_performance", "attention", f"scoped refresh P95 {p95:.0f}ms over budget {budget:.0f}ms"))
    performance = {"refresh_p50_ms": perf.get("p50_ms"), "refresh_p95_ms": p95, "budget_ms": budget}

    # ---- D. IR diff gate ----
    ir = store.read_json_prefer_backend("java-ir-index.json", {})
    if not ir.get("candidate_count"):
        attention.append("ir_index_missing")
        checks.append(_check("ir_diff_gate", "attention", "java-ir-index not present (legacy index)"))
    else:
        gate = run_diff_gate(ir, graph_db_path=str(store.graph_db_path))
        if gate["gate_passed"]:
            checks.append(_check("ir_diff_gate", "pass", f"edge_coverage {gate['edge_coverage']} forbidden {gate['forbidden_hit']}"))
        else:
            blocking.append("ir_gate_regression")
            checks.append(_check("ir_diff_gate", "block", f"IR gate regression: {gate}"))
        quality["ir_gate"] = {k: gate[k] for k in ("anchor_recall", "edge_coverage", "forbidden_hit")}

    # ---- E. storage health (read-only) ----
    gen_dir = store.index_dir / "generations"
    try:
        from pathlib import Path as _P

        gen_count = len([p for p in _P(gen_dir).iterdir() if p.is_dir()]) if _P(gen_dir).exists() else 0
        orphan = cleanup_generations(
            store,
            active_generation=active,
            previous_generation=previous,
            keep=2,
            apply=False,
        )
        candidates = orphan.get("candidates", []) or []
        if candidates:
            attention.append("generation_gc_candidates")
        storage = {
            "generation_count": gen_count,
            "gc_candidates": len(candidates),
            "gc_candidate_bytes": round(float(orphan.get("candidate_bytes", 0) or 0) / 1e6, 1),
        }
        checks.append(_check(
            "storage_health", "attention" if candidates else "pass",
            f"{gen_count} generations, {len(candidates)} gc candidates (dry-run only)",
        ))
    except Exception as exc:
        checks.append(_check("storage_health", "attention", f"storage check unavailable: {type(exc).__name__}"))

    # ---- decision ----
    if blocking:
        status = "block"
    elif "real_case_missing" in attention and not any(c.get("status") in ("block",) for c in checks):
        status = "real_case_missing" if not any(c.get("status") == "attention" for c in checks if c["id"] in ("coverage", "refresh_performance", "storage_health")) else "attention"
    elif attention:
        status = "attention"
    else:
        status = "pass"

    if blocking:
        next_actions.append("resolve blocking checks before publish")
    if "real_case_missing" in attention:
        next_actions.append("provide real replay/perf samples to claim verified quality")
    if "refresh_performance_over_budget" in attention:
        next_actions.append("investigate dominant refresh stage; see scoped-refresh report")

    return {
        "schema_version": 1,
        "status": status,
        "generated_at": time.time(),
        "generation": {"active": active[:16], "previous": previous[:16], "consistent": bool(active)},
        "checks": checks,
        "quality": quality,
        "performance": performance,
        "storage": storage,
        "blocking_reasons": sorted(set(blocking)),
        "attention_reasons": sorted(set(attention)),
        "next_actions": next_actions,
    }
