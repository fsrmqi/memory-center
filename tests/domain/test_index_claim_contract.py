"""Phase A contract regression tests (CODE_GRAPH_FOUNDATION_IMPLEMENTATION).

Covers the ``index_context`` / ``claim_boundary`` query contract:
coverage aggregation from the index pipeline, freshness/coverage
combination, the negative-claim gate across fresh/stale/partial/
not-indexed/truncated states, and additive schema compatibility of
existing facade responses.
"""
from __future__ import annotations

import pytest

from memory_center.core.freshness.contract import (
    FRESH,
    NOT_INDEXED,
    STALE,
    assemble_index_context,
    evaluate_claim_boundary,
)
from memory_center.core.indexing.coverage import CoverageLedger, write_coverage


# ---------------------------------------------------------------------------
# Unit: coverage ledger aggregation
# ---------------------------------------------------------------------------


def test_ledger_aggregates_counts_and_reasons():
    ledger = CoverageLedger()
    ledger.record("a/Baz.java", "parsed")
    ledger.record("b/broken.java", "failed", "parse_error")
    ledger.record("c/readme.md", "skipped", "unsupported_syntax")
    summary = ledger.summary()
    assert summary["parsed"] == 1
    assert summary["failed"] == 1
    assert summary["skipped"] == 1
    assert summary["total_files"] == 3
    codes = {row["code"]: row["count"] for row in summary["reasons"]}
    assert codes == {"parse_error": 1, "unsupported_syntax": 1}


def test_ledger_rows_are_deterministic():
    ledger = CoverageLedger()
    ledger.record("z/Zed.java", "parsed")
    ledger.record("a/App.java", "parsed")
    rows = [row["path"] for row in ledger.to_rows()]
    assert rows == sorted(rows)


def test_write_coverage_persists_snapshot(tmp_path):
    class _Store:
        def __init__(self):
            self.written = {}

        def write_json(self, name, data):
            self.written[name] = data

    store = _Store()
    ledger = CoverageLedger()
    ledger.record("x/X.java", "parsed")
    aggregate = write_coverage(store, "gen-test-1", ledger, mode="full")
    snapshot = store.written["index-coverage.json"]
    assert aggregate["parsed"] == 1
    assert snapshot["generation"] == "gen-test-1"
    assert snapshot["files"][0]["path"] == "x/X.java"


# ---------------------------------------------------------------------------
# Unit: claim boundary gate
# ---------------------------------------------------------------------------


def _context(**overrides):
    base = {
        "generation": "gen-1",
        "last_indexed_at": "2026-01-01T00:00:00",
        "request_tier": "standard",
        "freshness": FRESH,
        "coverage": {
            "scope_kind": "workspace",
            "requested_files": 10,
            "indexed_files": 10,
            "partial_files": 0,
            "skipped_files": 0,
            "failed_files": 0,
            "unknown_files": 0,
            "irrelevant_excluded": 0,
            "relevant_unsupported": 0,
            "reasons": [],
            "truncated": False,
        },
        "query_budget": {"depth": 3, "nodes": 80, "edges": 120, "timed_out": False},
    }
    base.update(overrides)
    return base


def test_fresh_full_coverage_empty_result_allows_negative_claim():
    gate = evaluate_claim_boundary(_context(), result_count=0)
    assert gate["negative_claim_allowed"] is True
    assert gate["reason_codes"] == []
    assert gate["evidence_level"] == "VERIFIED_NEGATIVE"


def test_positive_result_always_extracted():
    gate = evaluate_claim_boundary(_context(), result_count=5)
    assert gate["evidence_level"] == "EXTRACTED"
    # positive claims do not need the negative gate even when stale
    stale_gate = evaluate_claim_boundary(_context(freshness=STALE), result_count=5)
    assert stale_gate["reason_codes"] == ["generation_stale"]
    assert stale_gate["negative_claim_allowed"] is False


def test_stale_generation_blocks_negative_claim():
    gate = evaluate_claim_boundary(_context(freshness=STALE), result_count=0)
    assert gate["negative_claim_allowed"] is False
    assert "generation_stale" in gate["reason_codes"]
    assert gate["evidence_level"] == "AMBIGUOUS"


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    [
        ("partial_files", 2, "coverage_partial"),
        ("relevant_unsupported", 1, "coverage_partial"),
        ("failed_files", 1, "coverage_partial"),
        ("unknown_files", 3, "coverage_partial"),
        ("truncated", True, "query_truncated"),
    ],
)
def test_partial_coverage_blocks_negative_claim(field, value, expected_code):
    coverage = _context()["coverage"]
    coverage[field] = value
    gate = evaluate_claim_boundary(_context(coverage=coverage), result_count=0)
    assert gate["negative_claim_allowed"] is False
    assert expected_code in gate["reason_codes"]
    assert gate["evidence_level"] == "AMBIGUOUS"


def test_irrelevant_excluded_does_not_block_negative_claim():
    """Semantic calibration: explicitly irrelevant excluded resources
    (unsupported_syntax) never block a negative claim; only relevant
    unsupported / parse-failed / scope-unknown rows do."""
    coverage = _context()["coverage"]
    coverage["irrelevant_excluded"] = 500
    coverage["relevant_unsupported"] = 0
    gate = evaluate_claim_boundary(_context(coverage=coverage), result_count=0)
    assert gate["negative_claim_allowed"] is True
    assert "coverage_partial" not in gate["reason_codes"]


def test_timed_out_query_blocks_negative_claim():
    gate = evaluate_claim_boundary(_context(query_budget={"depth": 2, "nodes": 10, "edges": 5, "timed_out": True}), result_count=0)
    assert gate["negative_claim_allowed"] is False
    assert "query_timed_out" in gate["reason_codes"]


def test_not_published_blocks_everything():
    ctx = _context(generation="", freshness=NOT_INDEXED)
    gate = evaluate_claim_boundary(ctx, result_count=0)
    assert gate["negative_claim_allowed"] is False
    assert gate["reason_codes"] == ["index_not_published"]
    assert gate["evidence_level"] == "NOT_INDEXED"


# ---------------------------------------------------------------------------
# Integration: read model against a real indexed workspace
# ---------------------------------------------------------------------------


def test_assemble_index_context_on_indexed_workspace(demo_workspace_str):
    context = assemble_index_context(demo_workspace_str)
    assert context["generation"]
    assert context["freshness"] == FRESH
    coverage = context["coverage"]
    assert coverage["requested_files"] > 0
    assert coverage["indexed_files"] + coverage["skipped_files"] == coverage["requested_files"]
    assert any(row["code"] == "unsupported_syntax" for row in coverage["reasons"])
    # Semantic calibration: demo's skipped files are irrelevant resources
    # (unsupported_syntax), so they must be audited as irrelevant_excluded and
    # NOT block a negative claim on coverage grounds.
    assert coverage["irrelevant_excluded"] >= coverage["skipped_files"] or coverage["relevant_unsupported"] == 0
    gate = evaluate_claim_boundary(context, result_count=0)
    assert "coverage_partial" not in gate["reason_codes"]


def test_assemble_index_context_without_active_generation(demo_workspace):
    context = assemble_index_context(demo_workspace)
    assert context["generation"] == ""
    assert context["freshness"] == NOT_INDEXED
    gate = evaluate_claim_boundary(context)
    assert gate["negative_claim_allowed"] is False
    assert gate["evidence_level"] == "NOT_INDEXED"


def test_control_state_carries_coverage_summary(demo_workspace_str):
    from memory_center.core.indexing.control_plane import index_control_status
    from memory_center.core.storage.workspace import WorkspaceStore

    control = index_control_status(WorkspaceStore(demo_workspace_str))
    summary = control.get("coverage_summary", {})
    assert summary.get("total_files", 0) > 0
    assert summary.get("parsed", 0) + summary.get("skipped", 0) + summary.get("partial", 0) + summary.get("failed", 0) == summary.get("total_files")


# ---------------------------------------------------------------------------
# Facade additive-compat checks
# ---------------------------------------------------------------------------


def test_finalize_lookup_attaches_contract(demo_workspace_str):
    from memory_center.application.lookup import finalize_lookup, prepare_lookup

    prepared = prepare_lookup(demo_workspace_str, "OrderService", request_tier="standard", limit=20, depth=2, enable_vector=False, project="")
    payload: dict = {"mode_used": "symbol"}
    result = finalize_lookup(demo_workspace_str, "OrderService", payload, prepared, "mc_lookup")
    assert "index_context" in result and "claim_boundary" in result
    # pre-existing keys untouched (additive only)
    assert result["mode_used"] == "symbol"
    assert "auto_refresh" in result and "shard_route" in result


def test_finalize_lookup_attaches_primary_chain_only_for_method_anchor(demo_workspace_str):
    """primary_chain is additive and only present when best_match is a Method;
    never on a Class/DTO anchor, and never a fabricated chain."""
    from memory_center.application.lookup import finalize_lookup, prepare_lookup

    # Method anchor -> primary_chain attached with a valid contract shape.
    prepared = prepare_lookup(demo_workspace_str, "ArticleController.list", request_tier="standard", limit=10, depth=2, enable_vector=False, project="")
    payload = {
        "mode_used": "symbol",
        "result": {
            "found": True,
            "best_match": {
                "type": "Method",
                "id": "Method:article-service:ArticleController:list",
                "name": "ArticleController.list",
            },
            "matches": [],
        },
    }
    result = finalize_lookup(demo_workspace_str, "ArticleController.list", payload, prepared, "mc_lookup")
    pc = result.get("primary_chain")
    assert isinstance(pc, dict)
    assert pc["status"] in ("found", "not_found", "insufficient_evidence", "truncated")
    for key in ("status", "anchor", "steps", "score", "evidence_level", "generation", "reason_codes"):
        assert key in pc

    # Class anchor -> no primary_chain (never fabricate a chain from a class).
    prepared2 = prepare_lookup(demo_workspace_str, "OrderService", request_tier="standard", limit=10, depth=2, enable_vector=False, project="")
    payload2 = {
        "mode_used": "symbol",
        "result": {"found": True, "best_match": {"type": "Class", "id": "Class:api:OrderService", "name": "OrderService"}, "matches": []},
    }
    result2 = finalize_lookup(demo_workspace_str, "OrderService", payload2, prepared2, "mc_lookup")
    assert "primary_chain" not in result2


def test_change_review_plan_attaches_contract(demo_workspace):
    from memory_center.core.orchestrator.change_review import build_change_review_plan

    review = build_change_review_plan(demo_workspace, refresh=False)
    assert "index_context" in review and "claim_boundary" in review
    assert review["schema_version"] == 1
