"""Regression tests: hybrid retrieval fusion must default to pure functions.

P1 backlog item: ensure ``_merge_retrieval_results`` and
``_apply_type_boosting`` do not mutate caller-owned ``RetrievalResult``
objects (score, sources, evidence, neighbors, node, cross_workspace_refs).

These tests intentionally pass caller-constructed ``RetrievalResult`` lists in
and verify the original objects are unchanged after fusion.
"""

from __future__ import annotations

import copy

from memory_center.core.retrieval.hybrid import (
    HybridRetrievalConfig,
    RetrievalResult,
    _apply_type_boosting,
    _merge_retrieval_results,
)


def _make_hit(node_id: str, *, type_: str = "Class", score: float = 1.0) -> RetrievalResult:
    return RetrievalResult(
        node_id=node_id,
        node={"id": node_id, "type": type_, "name": node_id, "project": "demo", "file_path": f"src/{node_id}.java"},
        score=score,
        sources=["graph_exact"],
        evidence={"graph_rank": 1},
    )


def test_merge_does_not_mutate_score_or_sources() -> None:
    graph = [_make_hit("g1", score=2.0)]
    sparse = [_make_hit("s1", score=4.0)]
    semantic = [_make_hit("sm1", type_="Method", score=8.0)]
    snapshots = [
        (g, copy.deepcopy(g.sources), copy.deepcopy(g.evidence), g.score)
        for g in graph + sparse + semantic
    ]
    cfg = HybridRetrievalConfig()
    intent = {"primary_intent": "general"}
    _ = _merge_retrieval_results(graph, sparse, semantic, cfg, intent, query="g1")
    for hit, src_before, ev_before, score_before in snapshots:
        assert hit.score == score_before
        assert hit.sources == src_before
        assert hit.evidence == ev_before


def test_merge_does_not_mutate_node_dict() -> None:
    hit = _make_hit("g1")
    node_before = copy.deepcopy(hit.node)
    _ = _merge_retrieval_results([hit], [], [], HybridRetrievalConfig(), {}, query="g1")
    assert hit.node == node_before


def test_apply_type_boosting_does_not_mutate_caller_objects() -> None:
    hit = _make_hit("c1", type_="FeignClient", score=1.0)
    score_before = hit.score
    sources_before = list(hit.sources)
    evidence_before = dict(hit.evidence)
    boosted = _apply_type_boosting([hit], {"primary_intent": "feign"})
    # Boost is applied on the cloned list, not on the caller-owned object.
    assert hit.score == score_before
    assert hit.sources == sources_before
    assert hit.evidence == evidence_before
    # And the cloned hit reflects the boost.
    assert boosted[0].score >= score_before


def test_apply_type_boosting_returns_sorted_clones() -> None:
    # ``a`` and ``b`` start with the same score; under feign intent, Class
    # gets a structural penalty (0.75) and FeignClient gets a 1.5 boost,
    # so ``b`` should overtake ``a`` after type boosting.
    a = _make_hit("a", type_="Class", score=1.0)
    b = _make_hit("b", type_="FeignClient", score=1.0)
    out = _apply_type_boosting([a, b], {"primary_intent": "feign"})
    assert out[0].node_id == "b"
    # Inputs untouched by the call.
    assert a.score == 1.0
    assert b.score == 1.0


def test_repeated_calls_produce_stable_result_for_same_inputs() -> None:
    hits = [_make_hit("k1", score=2.0), _make_hit("k2", type_="FeignClient", score=1.0)]
    intent = {"primary_intent": "feign"}
    first = _apply_type_boosting(hits, intent)
    second = _apply_type_boosting(hits, intent)
    assert [r.node_id for r in first] == [r.node_id for r in second]
    assert [round(r.score, 6) for r in first] == [round(r.score, 6) for r in second]
