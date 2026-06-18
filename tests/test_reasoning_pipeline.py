from __future__ import annotations

from pathlib import Path

from memory_center.core.reasoning.models import ReasoningRequest
from memory_center.core.reasoning.pipeline import ReasoningPipeline
from memory_center.core.storage.unified import UnifiedStore


def _graph_store(tmp_path: Path) -> UnifiedStore:
    store = UnifiedStore(tmp_path / "graph.db")
    store.upsert_nodes(
        [
            ("Method:A#run", "Method", "A.run", "demo", "A.java", 10, "{}"),
            ("Method:B#work", "Method", "B.work", "demo", "B.java", 20, "{}"),
            ("Method:C#save", "Method", "C.save", "demo", "C.java", 30, "{}"),
        ]
    )
    store.upsert_edges(
        [
            ("edge:a-b", "Method:A#run", "Method:B#work", "CALLS_METHOD", 1.0, "{}"),
            ("edge:b-c", "Method:B#work", "Method:C#save", "CALLS_METHOD", 0.9, "{}"),
        ]
    )
    return store


def test_reasoning_pipeline_explains_transitive_risk(tmp_path: Path) -> None:
    store = _graph_store(tmp_path)
    try:
        result = ReasoningPipeline(store).analyze(
            ReasoningRequest("Method:A#run", "impact", 4, 20)
        )
    finally:
        store.close()

    assert result["facts"]
    assert result["derived"]
    assert result["quality"]["verification_required"] is True
    for item in result["inferences"] + result["derived"]:
        assert item["source_id"]
        assert item["relations"]
        assert 0.0 <= item["confidence"] <= 1.0
        assert item["why"]


def test_reasoning_pipeline_applies_one_global_evidence_budget(tmp_path: Path) -> None:
    store = _graph_store(tmp_path)
    try:
        result = ReasoningPipeline(store).analyze(
            ReasoningRequest("Method:A#run", "impact", 4, 2)
        )
    finally:
        store.close()

    total = len(result["facts"]) + len(result["inferences"]) + len(result["derived"])
    assert total <= 2
    assert result["quality"]["evidence_budget"] == 2
    assert result["quality"]["truncated"] is True


def test_reasoning_pipeline_can_be_disabled_without_graph_work(tmp_path: Path) -> None:
    store = _graph_store(tmp_path)
    try:
        result = ReasoningPipeline(store, enabled=False).analyze(
            ReasoningRequest("Method:A#run", "impact", 4, 20)
        )
    finally:
        store.close()

    assert result["facts"] == []
    assert result["inferences"] == []
    assert result["derived"] == []
    assert result["quality"]["status"] == "disabled"


def test_reasoning_pipeline_degrades_one_failed_engine(
    tmp_path: Path, monkeypatch,
) -> None:
    from memory_center.core.reasoning.patterns import GraphPatternEngine

    store = _graph_store(tmp_path)
    monkeypatch.setattr(
        GraphPatternEngine,
        "run_all_patterns",
        lambda _self: (_ for _ in ()).throw(RuntimeError("pattern failed")),
    )
    try:
        result = ReasoningPipeline(store).analyze(
            ReasoningRequest("Method:A#run", "audit", 4, 20)
        )
    finally:
        store.close()

    assert result["facts"]
    assert result["derived"]
    assert result["_diagnostics"]["graph_patterns"]["status"] == "unavailable"
    assert result["quality"]["status"] == "partial"


def test_reasoning_pipeline_filters_unrelated_workspace_patterns(tmp_path: Path) -> None:
    store = _graph_store(tmp_path)
    store.upsert_nodes(
        [
            (
                "MQConsumer:unrelated",
                "MQConsumer",
                "UnrelatedConsumer.consume",
                "other",
                "UnrelatedConsumer.java",
                1,
                '{"class_name":"UnrelatedConsumer","method_name":"consume","topic":"other"}',
            )
        ]
    )
    try:
        result = ReasoningPipeline(store).analyze(
            ReasoningRequest("Method:A#run", "impact", 4, 20)
        )
    finally:
        store.close()

    assert all(item["source_id"] != "MQConsumer:unrelated" for item in result["inferences"])


def test_target_reasoning_skips_workspace_pattern_scan(
    tmp_path: Path, monkeypatch,
) -> None:
    from memory_center.core.reasoning.patterns import GraphPatternEngine

    store = _graph_store(tmp_path)
    monkeypatch.setattr(
        GraphPatternEngine,
        "run_all_patterns",
        lambda _self: (_ for _ in ()).throw(AssertionError("global scan must not run")),
    )
    try:
        result = ReasoningPipeline(store).analyze(
            ReasoningRequest("Method:A#run", "walkthrough", 4, 8)
        )
    finally:
        store.close()

    assert result["derived"]
    assert "graph_patterns" not in result.get("_diagnostics", {})


def test_reasoning_integration_can_disable_pipeline(demo_workspace_indexed: Path) -> None:
    from memory_center.core.reasoning.integration import run_reasoning_patterns

    result = run_reasoning_patterns(
        str(demo_workspace_indexed),
        target_id="Method:any",
        enabled=False,
    )

    assert result["facts"] == []
    assert result["patterns"] == []
    assert result["quality"]["status"] == "disabled"


def test_reasoning_request_normalizes_limits() -> None:
    request = ReasoningRequest(" Method:A#run ", " IMPACT ", 0, 0)

    assert request.target_id == "Method:A#run"
    assert request.intent == "impact"
    assert request.max_depth == 1
    assert request.evidence_budget == 1


def test_reasoning_integration_exposes_pipeline_layers(demo_workspace_indexed: Path) -> None:
    from memory_center.core.graph import GraphStore
    from memory_center.core.reasoning.integration import run_reasoning_patterns
    from memory_center.core.store import WorkspaceStore

    workspace_store = WorkspaceStore(demo_workspace_indexed)
    with GraphStore(workspace_store.graph_db_path) as graph:
        target = graph.find_nodes("ArticleMoveService", types=["Class", "Method"], limit=1)[0]

    result = run_reasoning_patterns(
        str(demo_workspace_indexed),
        target_id=target["id"],
        max_transitive_depth=4,
        max_pattern_limit=20,
    )

    assert result["facts"]
    assert "inferences" in result
    assert "derived" in result
    assert result["quality"]["evidence_budget"] == 20
    assert "patterns" in result
    assert "transitive" in result
    assert "risk" in result


def test_lookup_and_walkthrough_include_additive_pipeline_reasoning(
    demo_workspace_indexed: Path,
) -> None:
    from memory_center.core.orchestrator.query import memory_context, memory_method_walkthrough

    context = memory_context(
        demo_workspace_indexed,
        "ArticleMoveService",
        max_depth=2,
    )
    walkthrough = memory_method_walkthrough(
        demo_workspace_indexed,
        "com.example.task.ArticleMoveService#move",
        depth=4,
        limit=80,
    )

    assert context["found"] is True
    assert context["node"]
    assert context["_reasoning"]["facts"]
    assert walkthrough["found"] is True
    assert walkthrough["target"]
    assert walkthrough["_reasoning"]["facts"]


def test_compact_lookup_impact_and_walkthrough_keep_reasoning_summary(
    demo_workspace_indexed: Path,
) -> None:
    from memory_center.core.orchestrator.impact import memory_impact
    from memory_center.core.orchestrator.query import memory_context, memory_method_walkthrough

    context = memory_context(
        demo_workspace_indexed,
        "ArticleMoveService",
        view="compact",
        budget="small",
    )
    impact = memory_impact(
        demo_workspace_indexed,
        "ArticleMoveService",
        view="compact",
        budget="small",
    )
    walkthrough = memory_method_walkthrough(
        demo_workspace_indexed,
        "com.example.task.ArticleMoveService#move",
        view="compact",
        budget="small",
    )

    for result in (context, impact, walkthrough):
        assert set(result["_reasoning"]) >= {"facts", "inferences", "derived", "quality"}
        assert len(result["_reasoning"]["facts"]) <= 2
        assert len(result["_reasoning"]["inferences"]) <= 2
        assert len(result["_reasoning"]["derived"]) <= 2
