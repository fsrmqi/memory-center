"""Phase D tests: explicit IR boundary and unified resolution diagnostics.

Covers CODE_GRAPH_FOUNDATION_IMPLEMENTATION §5.1 requirements:
deterministic stable ids (no rowid dependence), preservation of unproven
targets as AMBIGUOUS diagnostics instead of fabricated or dropped edges,
bounded reason-code aggregation, and symbol-category breakdowns for
regex-vs-AST parser differentials.
"""
from __future__ import annotations

from memory_center.core.indexing.differential import _symbol_category_counts
from memory_center.core.indexing.ir import (
    EVIDENCE_AMBIGUOUS,
    EVIDENCE_EXTRACTED,
    EVIDENCE_INFERRED,
    RelationCandidate,
    call_edges_to_relation_candidates,
    stable_id,
    summarize_unresolved,
    unresolved_by_file,
)


# ---------------------------------------------------------------------------
# Unit: IR primitives
# ---------------------------------------------------------------------------


def test_stable_id_is_deterministic_and_positional():
    a = stable_id("project", "path/A.java", "Method", "Order.process")
    b = stable_id("project", "path/A.java", "Method", "Order.process")
    c = stable_id("project", "path/A.java", "Method", "Order.ship")
    d = stable_id("path/A.java", "project", "Method", "Order.process")
    assert a == b
    assert a != c
    # order-sensitive so qualified identities cannot collide
    assert a != d


def test_call_edge_resolved_maps_to_extracted_candidate():
    edge = {
        "source_id": "S1",
        "target_id": "T1",
        "confidence": 0.95,
        "metadata": {"resolution_level": "same_class", "inferred_target": False},
    }
    candidates = call_edges_to_relation_candidates([edge])
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.target_ref == "T1"
    assert candidate.evidence_level == EVIDENCE_EXTRACTED
    assert candidate.relation == "CALLS_METHOD"
    assert candidate.resolution_reason == "same_class"


def test_inferred_target_maps_to_inferred_evidence():
    edge = {
        "source_id": "S1",
        "target_id": "T2",
        "confidence": 0.8,
        "metadata": {"resolution_level": "chain_return_type", "inferred_target": True},
    }
    candidate = call_edges_to_relation_candidates([edge])[0]
    assert candidate.evidence_level == EVIDENCE_INFERRED
    assert candidate.target_ref is not None


def test_unresolved_call_is_preserved_as_ambiguous_diagnostic():
    """Unproven targets must survive as diagnostics, never become fake edges."""
    edge = {
        "source_id": "S1",
        "target_id": "UnknownTarget",
        "confidence": 0.3,
        "metadata_json": '{"resolution_level": "unresolved", "unresolved_reason": "receiver_type_missing"}',
    }
    candidate = call_edges_to_relation_candidates([edge])[0]
    assert candidate.target_ref is None
    assert candidate.evidence_level == EVIDENCE_AMBIGUOUS
    assert candidate.resolution_reason == "receiver_type_missing"
    summary = summarize_unresolved([candidate])
    assert summary["total_calls"] == 1
    assert summary["unresolved"] == 1
    assert summary["resolved"] == 0
    assert summary["unresolved_reasons"] == [{"code": "receiver_type_missing", "count": 1}]


def test_duplicate_edges_are_deduplicated():
    edges = [
        {"source_id": "S1", "target_id": "T1", "confidence": 0.9, "metadata": {"resolution_level": "same_class"}},
        {"source_id": "S1", "target_id": "T1", "confidence": 0.9, "metadata": {"resolution_level": "same_class"}},
    ]
    candidates = call_edges_to_relation_candidates(edges)
    assert len(candidates) == 1


# ---------------------------------------------------------------------------
# Unit: aggregation helpers
# ---------------------------------------------------------------------------


def _candidates():
    return [
        RelationCandidate("s", "CALLS_METHOD", None, 0.3, "receiver_type_missing", EVIDENCE_AMBIGUOUS),
        RelationCandidate("s", "CALLS_METHOD", None, 0.3, "receiver_type_missing", EVIDENCE_AMBIGUOUS),
        RelationCandidate("s", "CALLS_METHOD", None, 0.3, "static_receiver_not_indexed", EVIDENCE_AMBIGUOUS),
        RelationCandidate("s", "CALLS_METHOD", "t", 0.9, "same_class", EVIDENCE_EXTRACTED),
    ]


def test_summarize_unresolved_counts_are_sorted_descending():
    summary = summarize_unresolved(_candidates())
    codes = [row["code"] for row in summary["unresolved_reasons"]]
    assert codes[0] == "receiver_type_missing"
    assert summary["total_calls"] == 4
    assert summary["resolved"] == 1
    assert summary["unresolved"] == 3
    assert summary["evidence_levels"][EVIDENCE_EXTRACTED] == 1
    assert summary["evidence_levels"][EVIDENCE_AMBIGUOUS] == 3


def test_unresolved_by_file_bounds_and_orders_output():
    candidates = [
        RelationCandidate(f"s{i}", "CALLS_METHOD", None, 0.3, "reason_a", EVIDENCE_AMBIGUOUS)
        for i in range(3)
    ] + [
        RelationCandidate("b", "CALLS_METHOD", None, 0.3, "reason_b", EVIDENCE_AMBIGUOUS),
    ]
    with_file = [
        RelationCandidate(
            c.source_key, c.relation, None, c.confidence, c.resolution_reason,
            EVIDENCE_AMBIGUOUS, source_file="a/FileA.java" if i < 3 else "b/FileB.java",
        )
        for i, c in enumerate(candidates)
    ]
    result = unresolved_by_file(with_file, max_files=1)
    assert list(result) == ["a/FileA.java"]
    assert result["a/FileA.java"] == {"reason_a": 3}


def test_symbol_category_counts_group_and_order():
    missing = [
        {"field": "method_calls", "identity": "x"},
        {"field": "method_calls", "identity": "y"},
        {"field": "classes", "identity": "z"},
    ]
    counted = _symbol_category_counts(missing)
    assert counted == [
        {"category": "method_calls", "count": 2},
        {"category": "classes", "count": 1},
    ]


# ---------------------------------------------------------------------------
# Integration: pipeline publishes diagnostics through the IR boundary
# ---------------------------------------------------------------------------


def test_reindex_publishes_resolution_diagnostics(demo_workspace_indexed):
    from memory_center.core.storage.workspace import WorkspaceStore

    store = WorkspaceStore(demo_workspace_indexed)
    payload = store.read_json_prefer_backend("index-resolution.json", {})
    assert payload.get("schema_version") == 1
    assert payload["total_calls"] > 0
    assert payload["resolved"] + payload["unresolved"] == payload["total_calls"]
    # Known resolver taxonomy only: short machine codes, no free text or code
    known_reasons = {
        "unresolved", "receiver_type_missing", "receiver_type_not_indexed",
        "target_method_not_indexed", "target_out_of_scope",
        "static_receiver_not_indexed", "static_receiver_without_visible_import",
        "external_static_call", "same_name_class_not_visible", "nested_type_static_call",
        "inherited_method_out_of_scope", "generated_enum_method_out_of_scope",
        "lombok_target_out_of_scope", "unqualified_or_dynamic",
    }
    for row in payload["unresolved_reasons"]:
        assert row["code"] in known_reasons

    summary = store.read_json_prefer_backend("graph-summary.json", {})
    rs = summary.get("resolution_summary", {})
    assert rs.get("calls_total", 0) == payload["total_calls"]
