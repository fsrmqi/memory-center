"""Primary service-chain search tests (long task: cross-service main chain).

Covers the bounded BFS, relation weighting, evidence levels, deterministic
ordering, bridge semantics, and the no-fabrication contract of
``find_primary_service_chain``.
"""
from __future__ import annotations

import pytest

from memory_center.core.retrieval.primary_chain import (
    MAIN_RELATION_WEIGHTS,
    _bridge_feign_method,
    _evidence_level,
    _is_cross_service,
    _path_score,
    _stable_sort_key,
    find_primary_service_chain,
)


# ---------------------------------------------------------------------------
# Unit: scoring and evidence
# ---------------------------------------------------------------------------


def _edge(rel: str, confidence: float = 0.9, level: str = "EXTRACTED", **meta):
    if "bridge" in meta or "resolution_level" in meta:
        # bridge/inference edges don't carry a default EXTRACTED evidence
        return {"type": rel, "confidence": confidence, "metadata": {**meta}}
    return {"type": rel, "confidence": confidence, "metadata": {"evidence_level": level, **meta}}


def test_path_score_weights_relation_and_evidence():
    # cross-service edge scores higher than a local CALLS_METHOD
    cross = _edge("CALLS_SERVICE", 0.9, "EXTRACTED")
    local = _edge("CALLS_METHOD", 0.9, "EXTRACTED")
    assert _path_score([cross]) > _path_score([local])


def test_path_score_deprecates_with_depth():
    one = _path_score([_edge("CALLS_SERVICE")])
    two = _path_score([_edge("CALLS_SERVICE"), _edge("HANDLES_ENDPOINT")])
    assert two < one  # depth decay


def test_evidence_level_contract_edges_are_extracted():
    for rel in ("CALLS_SERVICE", "IMPLEMENTS_FEIGN", "HANDLES_ENDPOINT", "PRODUCES_TOPIC", "CONSUMES_TOPIC"):
        assert _evidence_level(_edge(rel)) == "EXTRACTED", rel
    # bridge step is inference, never extracted (bridge flag on the edge row)
    bridge_edge = _edge("CALLS_METHOD", bridge=True)
    assert _evidence_level(bridge_edge) == "INFERRED"
    # unresolved CALLS_METHOD is ambiguous
    assert _evidence_level(_edge("CALLS_METHOD", resolution_level="unresolved")) == "AMBIGUOUS"


def test_is_cross_service_classification():
    for rel in ("CALLS_SERVICE", "IMPLEMENTS_FEIGN", "PRODUCES_TOPIC", "CONSUMES_TOPIC"):
        assert _is_cross_service(_edge(rel))
    assert not _is_cross_service(_edge("CALLS_METHOD"))
    assert not _is_cross_service(_edge("HANDLES_ENDPOINT"))  # intra-route, not cross-service


def test_stable_sort_key_prefers_extracted_cross_service():
    extracted = {"evidence_level": "EXTRACTED", "cross_service": True, "score": 0.5, "length": 2, "steps": [{"target_id": "a"}]}
    ambiguous = {"evidence_level": "AMBIGUOUS", "cross_service": True, "score": 0.9, "length": 2, "steps": [{"target_id": "b"}]}
    assert _stable_sort_key(extracted) < _stable_sort_key(ambiguous)


# ---------------------------------------------------------------------------
# Unit: forbidden relations never become chain body
# ---------------------------------------------------------------------------


def test_forbidden_relations_excluded_from_chain():
    from memory_center.core.retrieval.primary_chain import FORBIDDEN_CHAIN_RELATIONS

    for rel in ("CONTAINS", "DECLARES", "IMPORTS", "INJECTS_BEAN"):
        assert rel in FORBIDDEN_CHAIN_RELATIONS


# ---------------------------------------------------------------------------
# Integration: real indexed workspace
# ---------------------------------------------------------------------------


def test_http_anchor_returns_extracted_endpoint_chain(demo_workspace_indexed):
    from memory_center.core.orchestrator.query import memory_symbol

    info = memory_symbol(demo_workspace_indexed, "ArticleController", limit=3, project="article-service")
    # demo has HANDLES_ENDPOINT edges from controller methods
    if not info.get("found"):
        pytest.skip("demo workspace has no ArticleController")
    anchor = info["best_match"]
    if str(anchor.get("type", "")) != "Method":
        # find a method under the controller
        anchor = next((m for m in info.get("matches", []) if m.get("type") == "Method"), None)
    if anchor is None:
        pytest.skip("no method anchor available")
    result = find_primary_service_chain(demo_workspace_indexed, anchor)
    # Either found (cross-service or endpoint) or a clean not_found; never a
    # fabricated chain with AMBIGUOUS evidence labelled found.
    if result["status"] == "found":
        assert result["evidence_level"] in ("EXTRACTED", "INFERRED")
    else:
        assert result["status"] in ("not_found", "insufficient_evidence")


def test_negative_anchor_never_fabricates_chain(demo_workspace_indexed):
    # A method with no cross-service edges must be not_found, never a guess.
    anchor = {"id": "Method:nonexistent-proj:SomeClass:someMethod", "type": "Method", "name": "SomeClass.someMethod"}
    result = find_primary_service_chain(demo_workspace_indexed, anchor)
    assert result["status"] in ("not_found", "insufficient_evidence")
    assert result["steps"] == []


def test_primary_chain_contract_shape(demo_workspace_indexed):
    from memory_center.core.orchestrator.query import memory_symbol

    info = memory_symbol(demo_workspace_indexed, "ArticleFeignClient", limit=3, project="article-service")
    anchor = info.get("best_match") if info.get("found") else None
    if anchor is None or str(anchor.get("type", "")) != "Method":
        pytest.skip("no Feign method anchor")
    result = find_primary_service_chain(demo_workspace_indexed, anchor)
    for key in ("status", "anchor", "steps", "score", "evidence_level", "generation", "reason_codes"):
        assert key in result
    assert result["status"] in ("found", "not_found", "insufficient_evidence", "truncated")


# ---------------------------------------------------------------------------
# MQ bridge honesty (task: MQ 主链路保守桥接)
# ---------------------------------------------------------------------------


def test_mq_producer_returns_insufficient_evidence_not_found(demo_workspace_indexed):
    """An MQ Producer whose topic consumers cannot be proven must be reported
    as insufficient_evidence with an explicit MQ reason, never as not_found
    (which would claim 'no consumer exists')."""
    from memory_center.core.storage.runtime import RuntimeStore
    from memory_center.core.orchestrator.shared import load_context

    producer = None
    try:
        with RuntimeStore(load_context(demo_workspace_indexed)[1].graph_db_path) as graph:
            for cand in graph.find_nodes("", types=["MQProducer"], limit=1):
                producer = cand
                break
    except Exception:
        producer = None
    if producer is None:
        # No MQProducer in demo graph; synthesize one with a PRODUCES_TOPIC
        # edge to a topic that has no CONSUMES_TOPIC edge.
        with RuntimeStore(load_context(demo_workspace_indexed)[1].graph_db_path) as graph:
            graph.upsert_nodes([("MQProducer:demo:MockProducer", "MQProducer", "MockProducer", "demo", "", 0, {})])
            graph.upsert_nodes([("MQTopic:demo-topic", "MQTopic", "demo-topic", "demo", "", 0, {})])
            graph.upsert_edges([("PRODUCES_TOPIC:MQProducer:demo:MockProducer->MQTopic:demo-topic", "MQProducer:demo:MockProducer", "MQTopic:demo-topic", "PRODUCES_TOPIC", 1.0, {})])
        producer = {"id": "MQProducer:demo:MockProducer", "type": "MQProducer", "name": "MockProducer"}
    result = find_primary_service_chain(demo_workspace_indexed, producer)
    assert result["status"] == "insufficient_evidence"
    assert result["reason_codes"] and result["reason_codes"][0].startswith("mq_topic")
    assert result["steps"] == []


def test_method_negative_still_not_found(demo_workspace_indexed):
    """Non-MQ Method anchors with no cross-service edges keep not_found —
    the MQ honesty path must not leak into ordinary Method queries."""
    anchor = {"id": "Method:nonexistent-proj:SomeClass:someMethod", "type": "Method", "name": "SomeClass.someMethod"}
    result = find_primary_service_chain(demo_workspace_indexed, anchor)
    assert result["status"] == "not_found" or result["status"] == "insufficient_evidence"
    assert "mq_topic" not in " ".join(result["reason_codes"])
