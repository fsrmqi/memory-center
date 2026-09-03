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
from memory_center.core.indexing.coverage import coverage_for_scope
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
    # Semantic calibration: `unsupported_syntax` skipped files are explicitly
    # non-source resources (xml/png/json/md/...) that are irrelevant to any
    # Java query or change scope. They stay audited but never block a negative
    # claim or the release gate. Only relevant-unsupported, parse-failed, and
    # scope-unknown rows do.
    reason_counts = {str(r.get("code", "")): int(r.get("count", 0) or 0) for r in reasons}
    irrelevant_excluded = int(reason_counts.get("unsupported_syntax", 0) or 0)
    relevant_unsupported = max(0, int(summary.get("skipped", 0) or 0) - irrelevant_excluded)
    return {
        "scope_kind": "workspace",
        "requested_files": total,
        "indexed_files": parsed,
        "partial_files": int(summary.get("partial", 0) or 0),
        "skipped_files": int(summary.get("skipped", 0) or 0),
        "failed_files": int(summary.get("failed", 0) or 0),
        "unknown_files": unknown_files,
        "irrelevant_excluded": irrelevant_excluded,
        "relevant_unsupported": relevant_unsupported,
        "reasons": list(reasons) if coverage_known else [{"code": "coverage_unknown", "count": 1}],
        "truncated": False,
    }


def freshness_transition(index_context: dict[str, Any], observed_generation: str) -> str:
    """P2-C: compare a start-snapshot generation with the query's generation.

    快照 stale → 查询 fresh 时返回 ``stale_to_fresh``；generation 一致或快照
    为空返回空串。调用方（mc_lookup）据此提示 Agent 快照不是当前事实。
    """
    if not observed_generation or not index_context.get("generation"):
        return ""
    if str(observed_generation) == str(index_context.get("generation")):
        return ""
    if (
        index_context.get("freshness") == FRESH
        and str(index_context.get("generation")) != str(observed_generation)
    ):
        return "stale_to_fresh"
    return "generation_advanced"


def assemble_index_context(
    workspace_file: str | Any,
    *,
    request_tier: str = "standard",
    query_budget: dict[str, Any] | None = None,
    project: str = "",
    paths: list[str] | None = None,
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

    coverage = coverage_for_scope(store, project=project, paths=paths) if generation else {
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
        "truncated": False,
    }
    if isinstance(query_budget, dict):
        budget.update({key: query_budget[key] for key in budget if key in query_budget})
        budget["timed_out"] = bool(query_budget.get("timed_out", False))
        budget["truncated"] = bool(query_budget.get("truncated", False))

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
    chain_gate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive ``claim_boundary`` from an assembled ``index_context``.

    ``result_count > 0`` makes positive claims trivially allowed. An empty
    result set only earns ``negative_claim_allowed=True`` when every gate
    passes; otherwise evidence is degraded to AMBIGUOUS (or the
    NOT_INDEXED fact level when no generation was ever published).

    ``chain_gate`` (P1-A): chain/trace 结果附加的锚点与范围校验投影，
    ``{"anchor_status": "matched|mismatch|missing", "scope_incomplete": bool}``。
    锚定失败或路由未覆盖锚点项目时，空结果只是副作用而非负向证据，
    强制 ``anchor_mismatch`` / ``scope_incomplete`` reason code。
    """
    reason_codes: list[str] = []
    if not index_context.get("generation"):
        reason_codes.append("index_not_published")
    elif index_context.get("freshness") != FRESH:
        reason_codes.append("generation_stale")

    coverage = index_context.get("coverage", {}) if isinstance(index_context.get("coverage"), dict) else {}
    # Semantic calibration: explicitly irrelevant excluded resources
    # (unsupported_syntax: xml/png/json/md/...) never block a negative claim.
    # Only relevant-unsupported, parse-failed, and scope-unknown rows do.
    unclean = (
        int(coverage.get("partial_files", 0) or 0)
        + int(coverage.get("failed_files", 0) or 0)
        + int(coverage.get("unknown_files", 0) or 0)
        + int(coverage.get("relevant_unsupported", 0) or 0)
    )
    if unclean:
        reason_codes.append("coverage_partial")
    budget = index_context.get("query_budget") if isinstance(index_context.get("query_budget"), dict) else {}
    if coverage.get("truncated") or budget.get("truncated"):
        reason_codes.append("query_truncated")
    if budget.get("timed_out"):
        reason_codes.append("query_timed_out")
    try:
        from memory_center.core.orchestrator.chain_anchor_gate import gate_reasons_from_chain

        reason_codes.extend(gate_reasons_from_chain(chain_gate))
    except Exception:  # pragma: no cover - gate module always present in-tree
        pass

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


def attach_contract(payload: dict[str, Any], workspace_file: str | Any, *, query_budget: dict[str, Any] | None = None, result_count: int = 0, request_tier: str = "standard", project: str = "", paths: list[str] | None = None, chain_gate: dict[str, Any] | None = None) -> dict[str, Any]:
    """Convenience: attach both additive blocks onto a response payload."""
    index_context = assemble_index_context(workspace_file, request_tier=request_tier, query_budget=query_budget, project=project, paths=paths)
    payload["index_context"] = index_context
    payload["claim_boundary"] = evaluate_claim_boundary(index_context, result_count=result_count, chain_gate=chain_gate)
    return payload
