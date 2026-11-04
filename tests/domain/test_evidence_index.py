"""Evidence Index projection tests (MEMORY_ENRICHMENT_DESIGN.md capability A)."""
from __future__ import annotations

import pytest

from memory_center.core.orchestrator.evidence_index import (
    EVIDENCE_INDEX_MAX_LIMIT,
    build_evidence_index,
)


def _result(results, *, claim=None, total=None):
    return {
        "workspace": "ws",
        "results": results,
        "total_found": total if total is not None else len(results),
        "claim_boundary": claim if claim is not None else {"negative_claim_allowed": False, "evidence_level": "AMBIGUOUS"},
        "knowledge_state": {"state": "FRESH"},
        "freshness": {"freshness": {"status": "fresh"}},
    }


def test_projection_keeps_relative_paths_and_orders_by_score():
    result = _result(
        [
            {"node_id": "b", "node": {"type": "Class", "name": "B", "project": "gw", "file_path": "gw/src/B.java"}, "score": 0.4, "semantic_strength": "inferred"},
            {"node_id": "a", "node": {"type": "Class", "name": "A", "project": "gw", "file_path": "gw/src/A.java"}, "score": 0.9, "semantic_strength": "fact", "created_at": "2026-09-01T10:00:00+08:00"},
        ]
    )
    index = build_evidence_index(result, store=None, query="q")
    assert index["kind"] == "evidence_index"
    assert [item["ref_id"] for item in index["selected"]] == ["node:a", "node:b"]
    assert index["selected"][0]["created_at"] == "2026-09-01T10:00:00+08:00"
    assert index["selected"][0]["approx_tokens"] >= 1
    assert index["selected"][0]["estimated_tokens"] is True
    assert index["claim_boundary"] == {"negative_claim_allowed": False, "evidence_level": "AMBIGUOUS"}
    assert index["knowledge_state"] == "FRESH"
    assert index["freshness_status"] == "fresh"


def test_projection_drops_absolute_private_paths():
    result = _result(
        [
            {"node_id": "ok", "node": {"type": "Class", "name": "Ok", "project": "gw", "file_path": "gw/Ok.java"}, "score": 0.9, "semantic_strength": "fact"},
            {"node_id": "abs", "node": {"type": "Class", "name": "Abs", "project": "gw", "file_path": "/Users/private/secret/A.java"}, "score": 0.8, "semantic_strength": "fact"},
        ]
    )
    index = build_evidence_index(result, store=None, query="q")
    texts = " ".join(item["text"] for item in index["selected"])
    assert "/Users/private" not in texts
    assert any(item["ref_id"] == "node:ok" for item in index["selected"])


def test_projection_truncation_and_limit_bound():
    results = [
        {"node_id": f"n{i}", "node": {"type": "Class", "name": f"N{i}", "project": "gw"}, "score": 0.5, "semantic_strength": "inferred"}
        for i in range(30)
    ]
    index = build_evidence_index(_result(results), store=None, query="q", limit=10)
    assert index["returned"] == 10
    assert index["total_candidates"] == 30
    assert index["truncated"] is True
    capped = build_evidence_index(_result(results), store=None, query="q", limit=9999)
    assert capped["returned"] <= EVIDENCE_INDEX_MAX_LIMIT


def test_empty_result_preserves_negative_claim_gate():
    index = build_evidence_index(_result([], claim={"negative_claim_allowed": False, "evidence_level": "AMBIGUOUS"}), store=None, query="q")
    assert index["selected"] == []
    assert index["claim_boundary"]["negative_claim_allowed"] is False
    # A verified-negative boundary must survive the projection.
    verified = build_evidence_index(_result([], claim={"negative_claim_allowed": True, "evidence_level": "VERIFIED_NEGATIVE"}), store=None, query="q")
    assert verified["claim_boundary"]["negative_claim_allowed"] is True


def test_source_result_is_not_mutated():
    result = _result([{"node_id": "n", "node": {"type": "Class", "name": "N"}, "score": 0.5, "semantic_strength": "inferred"}])
    before = sorted(result.keys())
    build_evidence_index(result, store=None, query="q")
    assert sorted(result.keys()) == before
    assert "selected" not in result


def test_malformed_items_are_skipped():
    result = _result([None, "junk", {"node_id": "n", "node": {"type": "Class", "name": "N"}, "score": 0.5, "semantic_strength": "inferred"}])
    index = build_evidence_index(result, store=None, query="q")
    assert [item["ref_id"] for item in index["selected"]] == ["node:n"]


@pytest.mark.parametrize("bad_limit", [None, "x", -3])
def test_bad_limit_falls_back_to_default(bad_limit):
    result = _result([{"node_id": "n", "node": {"type": "Class", "name": "N"}, "score": 0.5, "semantic_strength": "inferred"}])
    index = build_evidence_index(result, store=None, query="q", limit=bad_limit)
    assert index["returned"] == 1
