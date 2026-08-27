"""Coverage read model and negative-claim gate (Phase A contract).

``assemble_index_context`` combines the published generation control state
(``index-control.json``), the freshness snapshot, and per-query budget
facts into the additive ``index_context`` block defined in
docs/decisions/CODE_GRAPH_FOUNDATION_IMPLEMENTATION.md §5.3.

``evaluate_claim_boundary`` is the logical gate for negative conclusions
("no callers", "no consumers", "no impact"): it returns
``negative_claim_allowed=True`` only when an active generation exists,
freshness is FRESH, the queried scope is fully covered, and the query was
neither truncated nor timed out. Callers must phrase anything else as
"not found within covered scope" — this gate cannot be overridden by
prompt wording.
"""
from __future__ import annotations

from typing import Any

from memory_center.core.freshness.status import IndexFreshnessService
from memory_center.core.indexing.control_plane import index_control_status
from memory_center.core.storage.workspace import WorkspaceStore

FRESH = "FRESH"
STALE = "STALE"
PARTIAL = "PARTIAL"
NOT_INDEXED = "NOT_INDEXED"

_FRESHNESS_MAP = {
    # IndexFreshnessService uses fresh|pending|stale|unknown; pending means
    # the source may have moved on after publication -> still queryable but
    # not eligible for negative claims.
    "fresh": FRESH,
    "pending": STALE,
    "stale": STALE,
    "unknown": STALE,
}


def _coverage_from_control(control: dict[str, Any]) -> dict[str, Any]:
    summary = control.get("coverage_summary") if isinstance(control.get("coverage_summary"), dict) else {}
    reasons = control.get("coverage_reasons") if isinstance(control.get("coverage_reasons"), list) else []
    total = int(summary.get("total_files", 0) or 0)
    parsed = int(summary.get("parsed", 0) or 0)
    unclean = total - parsed if total else 0
    # Workspaces indexed before the Phase A pipeline carry no per-file
    # ledger. Their true coverage is unknown and must never qualify for a
    # negative claim, even when they happen to be fresh.
    unknown_files = max(0, unclean - (
        int(summary.get("partial", 0) or 0)
        + int(summary.get("skipped", 0) or 0)
        + int(summary.get("failed", 0) or 0)
    ))
    coverage_known = bool(summary) and total > 0
    if not coverage_known:
        unknown_files = 1
    return {
        "scope_kind": "workspace",
        "requested_files": total,
        "indexed_files": parsed,
        "partial_files": int(summary.get("partial", 0) or 0),
        "skipped_files": int(summary.get("skipped", 0) or 0),
        "failed_files": int(summary.get("failed", 0) or 0),
        "unknown_files": unknown_files,
        "reasons": list(reasons) if coverage_known else [{"code": "coverage_unknown", "count": 1}],
        "truncated": False,
    }


def assemble_index_context(
    workspace_file: str | Any,
    *,
    request_tier: str = "standard",
    query_budget: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the additive ``index_context`` block for a task-level response."""
    store = WorkspaceStore(workspace_file)
    control = index_control_status(store)
    generation = str(control.get("active_generation", "") or "")
    try:
        banner = IndexFreshnessService(workspace_file).check()
        freshness_status = str(banner.status)
        last_indexed_at = banner.last_indexed_at
    except Exception:
        freshness_status = "unknown"
        last_indexed_at = ""

    if not generation:
        freshness = NOT_INDEXED
    elif freshness_status == "fresh":
        freshness = FRESH
    else:
        freshness = STALE

    coverage = _coverage_from_control(control) if generation else {
        "scope_kind": "workspace",
        "requested_files": 0,
        "indexed_files": 0,
        "partial_files": 0,
        "skipped_files": 0,
        "failed_files": 0,
        "unknown_files": 0,
        "reasons": [],
        "truncated": False,
    }

    budget: dict[str, Any] = {
        "depth": 0,
        "nodes": 0,
        "edges": 0,
        "timed_out": False,
    }
    if isinstance(query_budget, dict):
        budget.update({key: query_budget[key] for key in budget if key in query_budget})
        budget["timed_out"] = bool(query_budget.get("timed_out", False))

    return {
        "generation": generation,
        "last_indexed_at": last_indexed_at,
        "request_tier": request_tier,
        "freshness": freshness,
        "coverage": coverage,
        "query_budget": budget,
    }


def evaluate_claim_boundary(
    index_context: dict[str, Any],
    *,
    result_count: int = 0,
) -> dict[str, Any]:
    """Derive ``claim_boundary`` from an assembled ``index_context``.

    ``result_count > 0`` makes positive claims trivially allowed. An empty
    result set only earns ``negative_claim_allowed=True`` when every gate
    passes; otherwise evidence is degraded to AMBIGUOUS (or the
    NOT_INDEXED fact level when no generation was ever published).
    """
    reason_codes: list[str] = []
    if not index_context.get("generation"):
        reason_codes.append("index_not_published")
    elif index_context.get("freshness") != FRESH:
        reason_codes.append("generation_stale")

    coverage = index_context.get("coverage", {}) if isinstance(index_context.get("coverage"), dict) else {}
    unclean = (
        int(coverage.get("partial_files", 0) or 0)
        + int(coverage.get("skipped_files", 0) or 0)
        + int(coverage.get("failed_files", 0) or 0)
        + int(coverage.get("unknown_files", 0) or 0)
    )
    if unclean:
        reason_codes.append("coverage_partial")
    if coverage.get("truncated"):
        reason_codes.append("query_truncated")
    budget = index_context.get("query_budget") if isinstance(index_context.get("query_budget"), dict) else {}
    if budget.get("timed_out"):
        reason_codes.append("query_timed_out")

    gates_passed = not reason_codes
    negative_allowed = gates_passed and result_count == 0

    if result_count > 0:
        evidence_level = "EXTRACTED"
    elif not index_context.get("generation"):
        evidence_level = "NOT_INDEXED"
    elif negative_allowed:
        # Every gate passed: stating "absent within fully covered scope"
        # is a verified bounded conclusion.
        evidence_level = "VERIFIED_NEGATIVE"
    else:
        evidence_level = "AMBIGUOUS"

    return {
        "negative_claim_allowed": negative_allowed,
        "reason_codes": reason_codes,
        "evidence_level": evidence_level,
    }


def attach_contract(payload: dict[str, Any], workspace_file: str | Any, *, query_budget: dict[str, Any] | None = None, result_count: int = 0, request_tier: str = "standard") -> dict[str, Any]:
    """Convenience: attach both additive blocks onto a response payload."""
    index_context = assemble_index_context(workspace_file, request_tier=request_tier, query_budget=query_budget)
    payload["index_context"] = index_context
    payload["claim_boundary"] = evaluate_claim_boundary(index_context, result_count=result_count)
    return payload
