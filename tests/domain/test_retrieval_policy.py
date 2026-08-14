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

    def traverse_edges(self, _node_id, *, direction, max_depth, limit, edge_types=None):
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


def test_sparse_semantic_is_skipped_when_sqlite_bm25_is_ready() -> None:
    from memory_center.core.retrieval.hybrid import HybridRetrievalConfig, hybrid_retrieve

    graph = _RecordingGraph()

    def ready_bm25(*_args, diagnostics, **_kwargs):
        diagnostics["bm25"] = {"status": "active", "doc_count": 100}
        return []

    with (
        patch("memory_center.core.retrieval.hybrid._bm25_sparse_retrieval", side_effect=ready_bm25),
        patch("memory_center.core.retrieval.hybrid._semantic_retrieval") as semantic,
    ):
        result = hybrid_retrieve(
            graph,
            "/missing/workspace.yaml",
            "how are audit records persisted",
            config=HybridRetrievalConfig(enable_cross_workspace=False),
            freshness={"status": "fresh"},
        )

    semantic.assert_not_called()
    assert result["retrieval_diagnostics"]["semantic"]["reason"] == "redundant_sparse_semantic_bm25_active"


def test_hybrid_retrieval_reports_stage_timings_and_caches_same_generation() -> None:
    from memory_center.core.retrieval.hybrid import (
        _RETRIEVAL_CACHE,
        _RETRIEVAL_CACHE_LOCK,
        HybridRetrievalConfig,
        hybrid_retrieve,
    )

    graph = _RecordingGraph()
    config = HybridRetrievalConfig(enable_cross_workspace=False)
    with _RETRIEVAL_CACHE_LOCK:
        _RETRIEVAL_CACHE.clear()
    with (
        patch("memory_center.core.retrieval.hybrid._bm25_sparse_retrieval", return_value=[]) as bm25,
        patch("memory_center.core.retrieval.hybrid._semantic_retrieval", return_value=[]) as semantic,
    ):
        first = hybrid_retrieve(
            graph,
            "/missing/workspace.yaml",
            "how are audit records persisted",
            config=config,
            freshness={"status": "fresh"},
        )
        second = hybrid_retrieve(
            graph,
            "/missing/workspace.yaml",
            "how are audit records persisted",
            config=config,
            freshness={"status": "fresh"},
        )

    assert first["retrieval_diagnostics"]["cache"]["status"] == "miss"
    assert "semantic" in first["retrieval_diagnostics"]["timing_ms"]
    assert first["retrieval_diagnostics"]["timing_ms"]["total"] >= 0
    assert second["retrieval_diagnostics"]["cache"]["status"] == "hit"
    assert set(second["retrieval_diagnostics"]["timing_ms"]) == {"cache_lookup", "total"}
    assert bm25.call_count == 1
    assert semantic.call_count == 1


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


def test_verified_replay_calibration_requires_evidence_and_applies_only_after_threshold(tmp_path: Path) -> None:
    from memory_center.core.retrieval.calibration import evaluate_retrieval_replay_calibration
    from memory_center.core.verification.heuristics import (
        load_retrieval_source_weights,
        record_retrieval_source_feedback,
    )

    workspace = _workspace(tmp_path)
    for index in range(8):
        record_retrieval_source_feedback(
            workspace,
            intent="general",
            source="semantic",
            outcome="confirmed",
            evidence=[{"type": "human-review"}],
            task_id=f"task-{index}",
            weight_before=0.5,
        )
    # 无证据样本不会成为校准数据。
    record_retrieval_source_feedback(
        workspace,
        intent="general",
        source="semantic",
        outcome="confirmed",
        evidence=[],
    )

    preview = evaluate_retrieval_replay_calibration(workspace, min_samples=4)
    assert preview["status"] == "ready"
    assert preview["applied"] is False
    assert preview["proposals"]["general"]["semantic"]["sample_count"] == 8
    assert preview["proposals"]["general"]["semantic"]["validation_count"] == 2
    assert preview["proposals"]["general"]["semantic"]["validated"] is True

    applied = evaluate_retrieval_replay_calibration(workspace, min_samples=4, apply=True)
    assert applied["applied"] is True
    assert load_retrieval_source_weights(workspace, intent="general")["semantic"] == applied["applied_weights"]["general"]["semantic"]


def test_replay_calibration_deduplicates_task_and_blocks_holdout_regression(tmp_path: Path) -> None:
    from datetime import datetime, timedelta, timezone

    from memory_center.core.retrieval.calibration import evaluate_retrieval_replay_calibration
    from memory_center.core.verification.heuristics import HeuristicsRegister

    workspace = _workspace(tmp_path)
    register = HeuristicsRegister(workspace)
    started = datetime(2026, 1, 1, tzinfo=timezone.utc)
    outcomes = ["confirmed"] * 6 + ["rejected"] * 2
    for index, outcome in enumerate(outcomes):
        register.record_candidate_path_feedback(
            candidate_type="retrieval-source",
            target="general:semantic",
            outcome=outcome,
            evidence=[{"ref": f"e-{index}"}],
            task_id=f"task-{index}",
            recorded_at=(started + timedelta(minutes=index)).isoformat(),
            weight_before=0.5,
            category="retrieval-source",
        )
    register.record_candidate_path_feedback(
        candidate_type="retrieval-source",
        target="general:semantic",
        outcome="confirmed",
        evidence=[{"ref": "duplicate"}],
        task_id="task-0",
        recorded_at=(started + timedelta(minutes=9)).isoformat(),
        weight_before=0.5,
        category="retrieval-source",
    )

    result = evaluate_retrieval_replay_calibration(workspace, lookback_days=3650, min_samples=8, apply=True)

    assert result["discarded"]["duplicate"] == 1
    assert result["proposals"]["general"]["semantic"]["validated"] is False
    assert result["applied"] is False


def test_verified_replay_calibration_does_not_use_guidance_adoption_as_evidence(tmp_path: Path) -> None:
    from memory_center.core.retrieval.calibration import evaluate_retrieval_replay_calibration

    workspace = _workspace(tmp_path)
    result = evaluate_retrieval_replay_calibration(workspace, min_samples=1)
    assert result["status"] == "insufficient_replay"
    assert result["total_verified_samples"] == 0


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
    from memory_center.core.orchestrator.shared import load_context
    from memory_center.core.retrieval.hybrid import hybrid_retrieve
    from memory_center.core.storage.runtime import RuntimeStore

    _config, store = load_context(demo_workspace_indexed)
    with RuntimeStore(store.graph_db_path) as graph:
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
    assert first["action"] in {
        "refresh_or_read_live_files",
        "switch_to_walkthrough",
        "inspect_top_result",
        "validate_semantic_hit",
    }
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


def test_agent_next_steps_reinforce_actions_with_low_adoption(tmp_path: Path) -> None:
    from memory_center.core.benchmark.trending import record_agent_guidance_adoption_trend
    from memory_center.core.orchestrator.query import _build_agent_next_steps_for_query

    workspace = tmp_path / ".memory-center" / "workspace.yaml"
    workspace.parent.mkdir(parents=True)
    workspace.write_text("workspace: adoption-feedback\nroot: ..\nservices: []\n", encoding="utf-8")

    record_agent_guidance_adoption_trend(
        workspace,
        total_guidance_events=10,
        adopted_count=9,
        missed_count=1,
        adoption_rate=0.9,
        score=95,
        quality="high",
        missed_action_counts={"inspect_top_result": 1},
    )
    record_agent_guidance_adoption_trend(
        workspace,
        total_guidance_events=10,
        adopted_count=2,
        missed_count=8,
        adoption_rate=0.2,
        score=45,
        quality="low",
        missed_action_counts={"inspect_top_result": 8},
    )

    steps = _build_agent_next_steps_for_query(
        {
            "freshness": {"freshness": {"status": "fresh"}},
            "results": [{"node": {"type": "Class", "name": "ArticleService"}}],
        },
        query="ArticleService",
        workspace_file=workspace,
    )

    assert steps[0]["action"] == "inspect_top_result"
    assert steps[0]["priority"] == "high"
    assert steps[0]["adoption_feedback"]["status"] == "reinforced"
    assert steps[0]["adoption_feedback"]["missed_count"] == 8
    assert "low-adoption feedback" in steps[0]["command"]


def test_agent_next_steps_reinforce_actions_with_replay_feedback(tmp_path: Path) -> None:
    from memory_center.core.benchmark.trending import record_agent_guidance_replay_trend
    from memory_center.core.orchestrator.query import _build_agent_next_steps_for_query

    workspace = tmp_path / ".memory-center" / "workspace.yaml"
    workspace.parent.mkdir(parents=True)
    workspace.write_text("workspace: replay-feedback\nroot: ..\nservices: []\n", encoding="utf-8")

    record_agent_guidance_replay_trend(
        workspace,
        total_guidance_events=10,
        adopted_count=9,
        missed_count=1,
        bypassed_count=0,
        unobservable_count=0,
        adoption_rate=0.9,
        bypass_rate=0.0,
        unobservable_rate=0.0,
        score=95,
        quality="high",
        reason_counts={"matched_expected_tool": 9},
    )
    record_agent_guidance_replay_trend(
        workspace,
        total_guidance_events=10,
        adopted_count=2,
        missed_count=1,
        bypassed_count=6,
        unobservable_count=1,
        adoption_rate=0.2,
        bypass_rate=0.6,
        unobservable_rate=0.1,
        score=45,
        quality="low",
        reason_counts={"local_search_or_non_memory_tool_used": 6},
    )

    steps = _build_agent_next_steps_for_query(
        {
            "freshness": {"freshness": {"status": "fresh"}},
            "results": [{"node": {"type": "Class", "name": "ArticleService", "file_path": "src/ArticleService.java"}}],
        },
        query="ArticleService",
        workspace_file=workspace,
    )

    assert steps[0]["action"] == "inspect_top_result"
    assert steps[0]["priority"] == "high"
    assert steps[0]["target_ref"] == "src/ArticleService.java"
    assert steps[0]["read_targets"] == ["src/ArticleService.java"]
    assert steps[0]["replay_feedback"]["dominant_reason"] == "local_search_or_non_memory_tool_used"
    assert "replay feedback" in steps[0]["command"]
    assert "before rg/grep/find" in steps[0]["command"]


def test_agent_next_steps_replay_feedback_for_unobservable_sessions(tmp_path: Path) -> None:
    from memory_center.core.benchmark.trending import record_agent_guidance_replay_trend
    from memory_center.core.orchestrator.query import _build_agent_next_steps_for_query

    workspace = tmp_path / ".memory-center" / "workspace.yaml"
    workspace.parent.mkdir(parents=True)
    workspace.write_text("workspace: replay-unobservable\nroot: ..\nservices: []\n", encoding="utf-8")

    record_agent_guidance_replay_trend(
        workspace,
        total_guidance_events=10,
        adopted_count=9,
        missed_count=1,
        bypassed_count=0,
        unobservable_count=0,
        adoption_rate=0.9,
        bypass_rate=0.0,
        unobservable_rate=0.0,
        score=95,
        quality="high",
        reason_counts={"matched_expected_tool": 9},
    )
    record_agent_guidance_replay_trend(
        workspace,
        total_guidance_events=10,
        adopted_count=2,
        missed_count=1,
        bypassed_count=0,
        unobservable_count=7,
        adoption_rate=0.2,
        bypass_rate=0.0,
        unobservable_rate=0.7,
        score=45,
        quality="low",
        reason_counts={"no_followup_tool_call": 7},
    )

    steps = _build_agent_next_steps_for_query(
        {
            "freshness": {"freshness": {"status": "fresh"}},
            "results": [],
        },
        query="模糊问题",
        workspace_file=workspace,
    )

    assert steps[0]["action"] == "refine_query"
    assert steps[0]["replay_feedback"]["dominant_reason"] == "no_followup_tool_call"
    assert "session_id" in steps[0]["command"]


def test_agent_next_steps_replay_feedback_for_missing_target_hint(tmp_path: Path) -> None:
    from memory_center.core.benchmark.trending import record_agent_guidance_replay_trend
    from memory_center.core.orchestrator.query import _build_agent_next_steps_for_query

    workspace = tmp_path / ".memory-center" / "workspace.yaml"
    workspace.parent.mkdir(parents=True)
    workspace.write_text("workspace: replay-target\nroot: ..\nservices: []\n", encoding="utf-8")

    record_agent_guidance_replay_trend(
        workspace,
        total_guidance_events=10,
        adopted_count=9,
        missed_count=1,
        bypassed_count=0,
        unobservable_count=0,
        adoption_rate=0.9,
        bypass_rate=0.0,
        unobservable_rate=0.0,
        score=95,
        quality="high",
        reason_counts={"matched_expected_tool": 9},
    )
    record_agent_guidance_replay_trend(
        workspace,
        total_guidance_events=10,
        adopted_count=2,
        missed_count=8,
        bypassed_count=0,
        unobservable_count=0,
        adoption_rate=0.2,
        bypass_rate=0.0,
        unobservable_rate=0.0,
        score=45,
        quality="low",
        reason_counts={"guidance_missing_target_hint": 8},
    )

    steps = _build_agent_next_steps_for_query(
        {
            "freshness": {"freshness": {"status": "fresh"}},
            "retrieval_policy": {"primary_intent": "general"},
            "retrieval_diagnostics": {"semantic": {"status": "active"}},
            "results": [{"node": {"type": "Class", "name": "ArticleService", "abs_path": "/tmp/ArticleService.java"}}],
        },
        query="文章处理逻辑",
        workspace_file=workspace,
    )

    assert steps[0]["action"] == "validate_semantic_hit"
    assert steps[0]["target_required"] is True
    assert steps[0]["target_ref"] == "/tmp/ArticleService.java"
    assert "read_targets[0]" in steps[0]["command"]


def test_agent_next_steps_replay_feedback_for_action_mismatch(tmp_path: Path) -> None:
    from memory_center.core.benchmark.trending import record_agent_guidance_replay_trend
    from memory_center.core.orchestrator.query import _build_agent_next_steps_for_query

    workspace = tmp_path / ".memory-center" / "workspace.yaml"
    workspace.parent.mkdir(parents=True)
    workspace.write_text("workspace: replay-mismatch\nroot: ..\nservices: []\n", encoding="utf-8")

    record_agent_guidance_replay_trend(
        workspace,
        total_guidance_events=10,
        adopted_count=9,
        missed_count=1,
        bypassed_count=0,
        unobservable_count=0,
        adoption_rate=0.9,
        bypass_rate=0.0,
        unobservable_rate=0.0,
        score=95,
        quality="high",
        reason_counts={"matched_expected_tool": 9},
    )
    record_agent_guidance_replay_trend(
        workspace,
        total_guidance_events=10,
        adopted_count=2,
        missed_count=8,
        bypassed_count=0,
        unobservable_count=0,
        adoption_rate=0.2,
        bypass_rate=0.0,
        unobservable_rate=0.0,
        score=45,
        quality="low",
        reason_counts={"memory_tool_used_but_action_mismatch": 8},
    )

    steps = _build_agent_next_steps_for_query(
        {
            "freshness": {"freshness": {"status": "fresh"}},
            "results": [{"node": {"type": "Method", "name": "ArticleMoveService.move"}}],
        },
        query="ArticleMoveService.move",
        workspace_file=workspace,
    )

    assert steps[0]["action"] == "switch_to_walkthrough"
    assert steps[0]["replay_feedback"]["dominant_reason"] == "memory_tool_used_but_action_mismatch"
    assert "matches this action" in steps[0]["command"]


def test_method_level_agent_next_step_keeps_resolved_target_hint() -> None:
    from memory_center.core.orchestrator.query import _build_agent_next_steps_for_query

    steps = _build_agent_next_steps_for_query(
        {
            "freshness": {"freshness": {"status": "fresh"}},
            "results": [{"node": {
                "type": "Method",
                "name": "ArticleService.publish",
                "abs_path": "/repo/src/ArticleService.java",
            }}],
        },
        query="ArticleService#publish",
    )

    assert steps[0]["action"] == "switch_to_walkthrough"
    assert steps[0]["target_ref"] == "/repo/src/ArticleService.java"
    assert steps[0]["read_targets"] == ["/repo/src/ArticleService.java"]


def test_replay_campaign_requires_real_coverage_without_changing_weights(tmp_path: Path) -> None:
    from memory_center.core.orchestrator import memory_eval_agent_guidance_replay_campaign, workspace_log_session_event

    workspace = _workspace(tmp_path)
    workspace_log_session_event(
        workspace,
        "session-1",
        "agent_guidance",
        {
            "intent": "mq",
            "mode_used": "query",
            "retrieval_policy": {"sources": ["exact", "graph"]},
            "agent_next_steps": [{"action": "inspect_top_result", "command": "mc_lookup(mode=query)"}],
        },
    )
    workspace_log_session_event(workspace, "session-1", "tool_call", {"tool_name": "mc_lookup"})

    result = memory_eval_agent_guidance_replay_campaign(
        workspace,
        min_events=1,
        required_intents=("mq", "config"),
    )

    assert result["passed"] is False
    assert result["coverage"]["observed_intents"] == ["mq"]
    assert result["coverage"]["missing_intents"] == ["config"]
    assert result["replay"]["replay_records"][0]["retrieval_sources"] == ["exact", "graph"]
