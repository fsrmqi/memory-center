from __future__ import annotations

from pathlib import Path
from unittest.mock import patch


def test_full_chain_prefers_graph_and_disables_unneeded_vector() -> None:
    from memory_center.core.retrieval.policy import select_retrieval_policy

    policy = select_retrieval_policy(
        {"primary_intent": "walkthrough", "is_full_chain": True},
        {"status": "fresh"},
        {},
    )

    assert policy.sources[:2] == ("exact", "graph")
    assert policy.semantic_enabled is False
    assert policy.vector_enabled is False
    assert policy.graph_depth >= 4


def test_full_chain_symbol_suffix_still_matches_entry_method() -> None:
    from memory_center.core.retrieval.hybrid import _node_matches_query_name

    assert _node_matches_query_name(
        {"type": "Method", "name": "ArticleMoveService.move"},
        "ArticleMoveService#move 全链路",
    ) is True


def test_general_query_keeps_semantic_as_optional_source() -> None:
    from memory_center.core.retrieval.policy import select_retrieval_policy

    policy = select_retrieval_policy(
        {"primary_intent": "general"},
        {"status": "fresh"},
        {},
    )

    assert policy.sources[0] == "exact"
    assert "semantic" in policy.sources
    assert policy.semantic_enabled is True
    assert policy.vector_enabled is True


def test_stale_index_expands_evidence_without_unbounded_growth() -> None:
    from memory_center.core.retrieval.policy import select_retrieval_policy

    fresh = select_retrieval_policy(
        {"primary_intent": "general"}, {"status": "fresh"}, {}
    )
    stale = select_retrieval_policy(
        {"primary_intent": "general"}, {"status": "stale"}, {}
    )

    assert stale.candidate_limit >= fresh.candidate_limit
    assert stale.evidence_budget >= fresh.evidence_budget
    assert stale.candidate_limit <= 48
    assert stale.evidence_budget <= 12


def test_learned_weights_cannot_remove_hard_full_chain_sources() -> None:
    from memory_center.core.retrieval.policy import select_retrieval_policy

    learned = {"exact": 0.0, "graph": 0.0, "semantic": 0.0, "bm25": 1.0}
    policy = select_retrieval_policy(
        {"primary_intent": "walkthrough", "is_full_chain": True},
        {"status": "fresh"},
        learned,
    )

    assert policy.sources[:2] == ("exact", "graph")
    assert "semantic" not in policy.sources
    assert policy.candidate_limit <= 48


def test_learned_weights_cannot_remove_exact_graph_foundation() -> None:
    from memory_center.core.retrieval.policy import select_retrieval_policy

    policy = select_retrieval_policy(
        {"primary_intent": "general"},
        {"status": "fresh"},
        {"exact": 0.0, "graph": 0.0},
    )

    assert policy.sources[:2] == ("exact", "graph")


def test_policy_is_deterministic_and_does_not_mutate_inputs() -> None:
    from memory_center.core.retrieval.policy import select_retrieval_policy

    intent = {"primary_intent": "endpoint", "is_cross_service": True}
    freshness = {"status": "pending"}
    weights = {"bm25": 0.7, "semantic": 0.4}
    original = (dict(intent), dict(freshness), dict(weights))

    first = select_retrieval_policy(intent, freshness, weights)
    second = select_retrieval_policy(intent, freshness, weights)

    assert first == second
    assert (intent, freshness, weights) == original


class _RecordingGraph:
    def __init__(self, node_count: int = 1) -> None:
        self.find_limits: list[int] = []
        self.neighbor_depths: list[int] = []
        self.node_count = node_count

    def find_nodes(self, _query, *, types=None, limit=20):
        self.find_limits.append(limit)
        return [
            {
                "id": f"Method:demo:OrderService:move{index}",
                "type": "Method",
                "name": f"OrderService.move{index}",
                "project": "demo",
                "file_path": "OrderService.java",
            }
            for index in range(self.node_count)
        ]

    def neighbors(self, _node_id, *, direction, max_depth, limit, edge_types=None):
        self.neighbor_depths.append(max_depth)
        return []


def test_full_chain_policy_skips_semantic_and_vector_before_execution() -> None:
    from memory_center.core.retrieval.hybrid import HybridRetrievalConfig, hybrid_retrieve

    graph = _RecordingGraph(node_count=20)
    with (
        patch("memory_center.core.retrieval.hybrid._semantic_retrieval") as semantic,
        patch("memory_center.core.retrieval.hybrid._vector_retrieval") as vector,
        patch("memory_center.core.retrieval.hybrid._bm25_sparse_retrieval", return_value=[]) as bm25,
    ):
        result = hybrid_retrieve(
            graph,
            "/missing/workspace.yaml",
            "OrderService#move 全链路",
            config=HybridRetrievalConfig(enable_vector=True, enable_cross_workspace=False),
            freshness={"status": "fresh"},
        )

    semantic.assert_not_called()
    vector.assert_not_called()
    bm25.assert_not_called()
    assert result["retrieval_policy"]["sources"][:2] == ["exact", "graph"]
    assert result["retrieval_diagnostics"]["semantic"]["reason"] == "policy_off"
    assert result["retrieval_diagnostics"]["vector"]["reason"] == "policy_off"


def test_policy_controls_candidate_limit_and_neighbor_budget() -> None:
    from memory_center.core.retrieval.hybrid import HybridRetrievalConfig, hybrid_retrieve

    graph = _RecordingGraph()
    with patch(
        "memory_center.core.retrieval.hybrid._bm25_sparse_retrieval", return_value=[]
    ):
        result = hybrid_retrieve(
            graph,
            "/missing/workspace.yaml",
            "OrderService#move 全链路",
            config=HybridRetrievalConfig(enable_cross_workspace=False),
            freshness={"status": "fresh"},
            limit=20,
        )

    assert graph.find_limits[0] == result["retrieval_policy"]["candidate_limit"]
    assert graph.neighbor_depths == [4, 4]
    assert result["retrieval_policy"]["evidence_budget"] == 8


def test_full_chain_caps_returned_results_to_evidence_budget() -> None:
    from memory_center.core.retrieval.hybrid import HybridRetrievalConfig, hybrid_retrieve

    graph = _RecordingGraph(node_count=20)
    with patch(
        "memory_center.core.retrieval.hybrid._bm25_sparse_retrieval", return_value=[]
    ):
        result = hybrid_retrieve(
            graph,
            "/missing/workspace.yaml",
            "OrderService#move 全链路",
            config=HybridRetrievalConfig(enable_cross_workspace=False),
            freshness={"status": "fresh"},
            limit=20,
        )

    assert result["returned"] <= result["retrieval_policy"]["evidence_budget"]
    # One retrieval traversal plus at most two result-enrichment traversals.
    assert len(graph.neighbor_depths) <= 3
    assert set(graph.neighbor_depths) == {4}


def test_general_policy_allows_explicit_vector_and_semantic_execution() -> None:
    from memory_center.core.retrieval.hybrid import HybridRetrievalConfig, hybrid_retrieve

    graph = _RecordingGraph()
    with (
        patch("memory_center.core.retrieval.hybrid._semantic_retrieval", return_value=[]) as semantic,
        patch("memory_center.core.retrieval.hybrid._vector_retrieval", return_value=[]) as vector,
        patch("memory_center.core.retrieval.hybrid._bm25_sparse_retrieval", return_value=[]),
    ):
        hybrid_retrieve(
            graph,
            "/missing/workspace.yaml",
            "how are audit records persisted",
            config=HybridRetrievalConfig(enable_vector=True, enable_cross_workspace=False),
            freshness={"status": "fresh"},
        )

    semantic.assert_called_once()
    vector.assert_called_once()


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / ".memory-center" / "workspace.yaml"
    workspace.parent.mkdir(parents=True)
    workspace.write_text(
        f"workspace: retrieval-policy\nroot: {tmp_path.as_posix()}\nservices: []\n",
        encoding="utf-8",
    )
    return workspace


def test_retrieval_feedback_is_bounded_and_scoped_by_intent(tmp_path: Path) -> None:
    from memory_center.core.verification.heuristics import (
        load_retrieval_source_weights,
        record_retrieval_source_feedback,
    )

    workspace = _workspace(tmp_path)
    record_retrieval_source_feedback(
        workspace,
        intent="general",
        source="semantic",
        outcome="confirmed",
        evidence=["verified-result"],
        weight_before=0.74,
    )
    record_retrieval_source_feedback(
        workspace,
        intent="endpoint",
        source="semantic",
        outcome="rejected",
        evidence=["false-positive"],
        weight_before=0.36,
    )

    general = load_retrieval_source_weights(workspace, intent="general")
    endpoint = load_retrieval_source_weights(workspace, intent="endpoint")

    assert general == {"semantic": 0.75}
    assert endpoint == {"semantic": 0.35}


def test_bounded_retrieval_weights_ignore_unknown_sources() -> None:
    from memory_center.core.verification.heuristics import bounded_retrieval_source_weights

    bounded = bounded_retrieval_source_weights(
        {"graph": 100, "semantic": -1, "unknown": 0.6, "bm25": "bad"}
    )

    assert bounded == {"graph": 0.75, "semantic": 0.35}


def test_memory_query_passes_freshness_and_learned_weights_once(
    demo_workspace_indexed: Path, monkeypatch,
) -> None:
    from memory_center.core.freshness.status import IndexFreshnessService
    from memory_center.core.orchestrator.query import memory_query_hybrid
    from memory_center.core.retrieval import hybrid as hybrid_module
    from memory_center.core.verification import heuristics as heuristics_module

    captured = {}
    banner_calls = 0

    def fake_hybrid(*_args, **kwargs):
        captured.update(kwargs)
        return {
            "query": kwargs["query"],
            "intent": {"primary_intent": "general"},
            "results": [],
            "retrieval_summary": {},
            "progressive": {},
            "retrieval_diagnostics": {},
        }

    def fake_banner(_self):
        nonlocal banner_calls
        banner_calls += 1
        return {"freshness": {"status": "fresh"}, "banner": None}

    monkeypatch.setattr(hybrid_module, "hybrid_retrieve", fake_hybrid)
    monkeypatch.setattr(IndexFreshnessService, "banner", fake_banner)
    monkeypatch.setattr(
        heuristics_module,
        "load_retrieval_source_weights",
        lambda *_args, **_kwargs: {"semantic": 0.7},
    )

    result = memory_query_hybrid(
        demo_workspace_indexed,
        "how are audit records persisted",
        limit=10,
    )

    assert captured["freshness"] == {"status": "fresh"}
    assert captured["learned_weights"] == {"semantic": 0.7}
    assert banner_calls == 1
    assert result["freshness"]["freshness"]["status"] == "fresh"


def test_full_chain_budget_keeps_entry_method_anchor(demo_workspace_indexed: Path) -> None:
    from memory_center.core.graph import GraphStore
    from memory_center.core.orchestrator.common import load_context
    from memory_center.core.retrieval.hybrid import hybrid_retrieve

    _config, store = load_context(demo_workspace_indexed)
    with GraphStore(store.graph_db_path) as graph:
        result = hybrid_retrieve(
            graph,
            str(demo_workspace_indexed),
            "ArticleMoveService#move 全链路",
            limit=80,
        )
    rows = [
        (
            item.get("node", {}).get("name"),
            item.get("score"),
            item.get("sources"),
        )
        for item in result["results"]
    ]

    assert any(name == "ArticleMoveService.move" for name, _score, _sources in rows), rows


def test_full_chain_symbol_query_routes_to_walkthrough(demo_workspace_indexed: Path) -> None:
    from memory_center.core.orchestrator.query import memory_query_hybrid

    result = memory_query_hybrid(
        demo_workspace_indexed,
        "梳理下 com.example.task.ArticleMoveService#move 全链路 一直到最底层的逻辑处理",
        limit=20,
        project="task-service",
    )

    assert result["mode_used"] == "query_walkthrough"
    assert result["query_symbol"] == "com.example.task.ArticleMoveService#move"
    assert result["found"] is True
    assert result["target"]["class"] == "ArticleMoveService"
    assert result["target"]["method"] == "move"
    assert result["summary_lines"]
    assert any("ArticleController#moveArticle" in line for line in result["summary_lines"])
    assert result["agent_usage_policy"]["read_files_by"] == "absolute_file_path"
    assert result["completion_status"]["state"] == "complete"
    assert result["completion_status"]["recommended_action"] == "use_current_evidence"
    assert result["agent_next_steps"][0]["action"] == "use_read_targets"
    assert "do not run find/grep-l" in result["agent_next_steps"][0]["command"]


def test_hybrid_query_returns_structured_agent_next_steps(demo_workspace_indexed: Path) -> None:
    from memory_center.core.orchestrator.query import memory_query_hybrid

    result = memory_query_hybrid(
        demo_workspace_indexed,
        "ArticleFeignClient",
        limit=10,
        project="task-service",
    )

    assert result["results"]
    assert result["agent_next_steps"]
    first = result["agent_next_steps"][0]
    assert first["action"] in {"switch_to_walkthrough", "inspect_top_result", "validate_semantic_hit"}
    assert first["priority"] in {"high", "medium"}
    assert first["command"]
    assert isinstance(first["uses_existing_evidence"], bool)


def test_agent_next_steps_prioritize_stale_evidence_before_search() -> None:
    from memory_center.core.orchestrator.query import _build_agent_next_steps_for_query

    steps = _build_agent_next_steps_for_query(
        {
            "freshness": {"freshness": {"status": "stale"}},
            "results": [{"node": {"type": "Class", "name": "ArticleService"}}],
        },
        query="ArticleService",
    )

    assert steps[0]["action"] == "refresh_or_read_live_files"
    assert steps[0]["priority"] == "high"
    assert "read matched files live" in steps[0]["command"]


def test_agent_next_steps_refine_when_query_has_no_evidence() -> None:
    from memory_center.core.orchestrator.query import _build_agent_next_steps_for_query

    steps = _build_agent_next_steps_for_query(
        {
            "freshness": {"freshness": {"status": "fresh"}},
            "results": [],
        },
        query="模糊问题",
    )

    assert steps[0]["action"] == "refine_query"
    assert steps[0]["uses_existing_evidence"] is False


def test_agent_next_steps_validate_semantic_general_hits() -> None:
    from memory_center.core.orchestrator.query import _build_agent_next_steps_for_query

    steps = _build_agent_next_steps_for_query(
        {
            "freshness": {"freshness": {"status": "fresh"}},
            "retrieval_policy": {"primary_intent": "general"},
            "retrieval_diagnostics": {"semantic": {"status": "active"}},
            "results": [{"node": {"type": "Class", "name": "ArticleService"}}],
        },
        query="文章处理逻辑",
    )

    assert steps[0]["action"] == "validate_semantic_hit"
    assert "verify" in steps[0]["reason"]


def test_agent_next_steps_switch_to_walkthrough_for_method_hits() -> None:
    from memory_center.core.orchestrator.query import _build_agent_next_steps_for_query

    steps = _build_agent_next_steps_for_query(
        {
            "freshness": {"freshness": {"status": "fresh"}},
            "results": [{"node": {"type": "Method", "name": "ArticleMoveService.move"}}],
        },
        query="ArticleMoveService.move",
    )

    assert steps[0]["action"] == "switch_to_walkthrough"
    assert "mode=\"walkthrough\"" in steps[0]["command"]
