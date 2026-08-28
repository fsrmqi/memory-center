"""Retrieval replay runner unit tests (long task).

Covers case loading, outcome classification, and aggregation. These are
pure-logic tests (no graph dependency) so the evaluation harness is reliable
independent of any workspace.
"""
from __future__ import annotations

import pytest

from memory_center.core.benchmark.retrieval_replay import (
    ANCHOR_RANKED_LOW,
    CHAIN_MISSING,
    CHAIN_WRONG,
    DATASET_WRONG,
    EVIDENCE_BOUNDARY,
    PASS,
    RetrievalReplayCase,
    aggregate_replay,
    classify_outcome,
    load_replay_cases,
)


def _case(intent: str, expected: dict | None = None) -> RetrievalReplayCase:
    return RetrievalReplayCase(
        case_id=f"c-{intent}",
        intent_class=intent,
        query_ref="ref",
        expected=expected or {},
    )


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def test_feign_chain_found_is_pass():
    case = _case("feign_chain", {"primary_chain": {"status": "found"}})
    result = {"best_match": {"kind": "Method", "rank": 1}, "primary_chain": {"status": "found"}}
    assert classify_outcome(case, result) == PASS


def test_feign_chain_missing_with_graph_evidence():
    case = _case("feign_chain", {"primary_chain": {"status": "found"}})
    result = {"best_match": {"kind": "Method", "rank": 1}, "primary_chain": {"status": "not_found"}}
    assert classify_outcome(case, result) == CHAIN_MISSING


def test_negative_not_found_is_boundary():
    case = _case("negative")
    result = {"primary_chain": {"status": "not_found"}, "best_match": {"kind": "Method", "rank": 1}}
    assert classify_outcome(case, result) == EVIDENCE_BOUNDARY


def test_negative_found_is_wrong_chain():
    case = _case("negative")
    result = {"primary_chain": {"status": "found"}, "best_match": {"kind": "Method", "rank": 1}}
    assert classify_outcome(case, result) == CHAIN_WRONG


def test_mq_insufficient_is_boundary():
    case = _case("mq_producer")
    result = {"primary_chain": {"status": "insufficient_evidence"}, "best_match": {"kind": "MQProducer", "rank": 1}}
    assert classify_outcome(case, result) == EVIDENCE_BOUNDARY


def test_mq_unreachable_anchor_is_dataset_wrong():
    case = _case("mq_producer")
    result = {"primary_chain": {"status": None}, "best_match": {"kind": "Field", "rank": 1}}
    assert classify_outcome(case, result) == DATASET_WRONG


def test_same_name_respects_expected_class_kind():
    case = _case("same_name", {"anchor": {"kind": "Class"}})
    result = {"best_match": {"kind": "Class", "rank": 1}, "primary_chain": {"status": None}}
    assert classify_outcome(case, result) == PASS


def test_same_name_method_query_displaced_is_ranked_low():
    case = _case("same_name", {"anchor": {"kind": "Method"}})
    result = {"best_match": {"kind": "Class", "rank": 1}, "primary_chain": {"status": None}}
    assert classify_outcome(case, result) == ANCHOR_RANKED_LOW


def test_stale_boundary_refuses_negative_claim():
    case = _case("stale_boundary")
    result = {"claim_boundary": {"negative_claim_allowed": False}, "best_match": {"kind": None, "rank": 0}}
    assert classify_outcome(case, result) == EVIDENCE_BOUNDARY


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def test_aggregate_metrics():
    outcomes = [
        {"intent_class": "feign_chain", "classification": PASS, "best_match": {"kind": "Method", "rank": 1}, "primary_chain": {"status": "found"}, "performance": {"latency_ms": 10}},
        {"intent_class": "feign_chain", "classification": CHAIN_MISSING, "best_match": {"kind": "Method", "rank": 1}, "primary_chain": {"status": "not_found"}, "performance": {"latency_ms": 20}},
        {"intent_class": "mq_producer", "classification": EVIDENCE_BOUNDARY, "best_match": {"kind": "MQProducer", "rank": 1}, "primary_chain": {"status": "insufficient_evidence"}, "performance": {"latency_ms": 30}},
        {"intent_class": "negative", "classification": EVIDENCE_BOUNDARY, "best_match": {"kind": "Method", "rank": 1}, "primary_chain": {"status": "not_found"}, "performance": {"latency_ms": 40}},
    ]
    agg = aggregate_replay(outcomes)
    assert agg["case_count"] == 4
    assert agg["outcomes"][PASS] == 1
    assert agg["outcomes"][EVIDENCE_BOUNDARY] == 2
    # anchor top1: 2 anchor-eligible (feign) both rank1 Method -> 1.0
    assert agg["quality"]["anchor_top1_recall"] == 1.0
    # primary chain recall: 1 of 2 feign found -> 0.5
    assert agg["quality"]["primary_chain_recall"] == 0.5
    assert agg["quality"]["wrong_chain_rate"] == 0.0
    assert agg["performance"]["p50_ms"] == 25.0  # median of 10,20,30,40


def test_load_replay_cases_parses_yaml(tmp_path):
    f = tmp_path / "cases.yaml"
    f.write_text(
        "schema_version: 1\ncases:\n"
        "  - id: a\n    intent_class: feign_chain\n    query_ref: q1\n"
        "    expected:\n      primary_chain: {status: found}\n"
        "  - id: b\n    intent_class: negative\n    query_ref: q2\n",
        encoding="utf-8",
    )
    cases = load_replay_cases(f)
    assert len(cases) == 2
    assert cases[0].case_id == "a"
    assert cases[0].expected["primary_chain"]["status"] == "found"
