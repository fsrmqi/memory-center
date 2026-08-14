from __future__ import annotations

import subprocess
from pathlib import Path

from memory_center.core.benchmark.cochange import evaluate_git_cochange
from memory_center.core.knowledge.communities import analyze_architecture_communities
from memory_center.core.orchestrator.change_review import build_change_review_plan
from memory_center.core.orchestrator.impact import _parse_git_name_status
from memory_center.core.storage.graph import GraphEdge, GraphNode
from memory_center.core.storage.runtime import RuntimeStore
from memory_center.core.storage.workspace import WorkspaceStore


def _workspace(tmp_path: Path, services: str = "services: []") -> Path:
    root = tmp_path / "workspace"
    memory = root / ".memory-center"
    memory.mkdir(parents=True)
    workspace = memory / "workspace.yaml"
    workspace.write_text(
        f"workspace: p0-test\nroot: {root.as_posix()}\n{services}\n",
        encoding="utf-8",
    )
    return workspace


def test_git_change_parser_tracks_delete_and_rename_without_extra_processes() -> None:
    changed, deleted = _parse_git_name_status(
        "M\0src/A.java\0D\0src/Old.java\0R100\0src/Before.java\0src/After.java\0",
        "service",
    )

    assert changed == ["service/src/A.java", "service/src/Old.java", "service/src/After.java"]
    assert deleted == ["service/src/Old.java", "service/src/Before.java"]


def test_weighted_impact_keeps_best_path_and_bounds_cycles(tmp_path: Path) -> None:
    with RuntimeStore(tmp_path / "graph.db") as graph:
        graph.rebuild(
            [
                GraphNode("caller", "Method", "caller", "api", "src/Caller.java"),
                GraphNode("middle", "Method", "middle", "service", "src/Middle.java"),
                GraphNode("target", "Method", "target", "service", "src/Target.java"),
                GraphNode("weak", "Class", "weak", "api", "src/Weak.java"),
            ],
            [
                GraphEdge("caller-middle", "caller", "middle", "CALLS_METHOD", 1.0),
                GraphEdge("middle-target", "middle", "target", "CALLS_METHOD", 1.0),
                GraphEdge("target-caller", "target", "caller", "CALLS_METHOD", 0.9),
                GraphEdge("weak-target", "weak", "target", "IMPORTS", 0.8),
            ],
        )
        impacts = graph.weighted_impact_paths("target", direction="upstream", max_depth=5, limit=10)

    by_endpoint = {
        row["best_path"]["node_ids"][-1]: row
        for row in impacts
    }
    assert set(by_endpoint) == {"middle", "caller", "weak"}
    assert by_endpoint["middle"]["impact_score"] > by_endpoint["caller"]["impact_score"]
    assert by_endpoint["caller"]["best_path"]["node_ids"] == ["target", "middle", "caller"]
    assert by_endpoint["weak"]["impact_score"] < by_endpoint["middle"]["impact_score"]
    assert impacts[0]["traversal"]["algorithm"] == "bounded_weighted_best_path_v1"


def test_weighted_impact_exposes_but_does_not_expand_alternative_relations(tmp_path: Path) -> None:
    with RuntimeStore(tmp_path / "graph.db") as graph:
        graph.rebuild(
            [
                GraphNode("source", "File", "Source.java"),
                GraphNode("target", "File", "Target.java"),
                GraphNode("next", "Method", "next"),
            ],
            [
                GraphEdge("strong", "source", "target", "CALLS_METHOD", 1.0),
                GraphEdge("weak", "source", "target", "IMPORTS", 0.8),
                GraphEdge("next-hop", "target", "next", "CALLS_METHOD", 1.0),
            ],
        )
        impacts = graph.weighted_impact_paths("source", direction="downstream", max_depth=3, limit=20)

    target_rows = [row for row in impacts if row["best_path"]["node_ids"][-1] == "target"]
    assert len([row for row in target_rows if not row.get("alternative_path_evidence")]) == 1
    assert any(row.get("alternative_path_evidence") and row["type"] == "IMPORTS" for row in target_rows)
    assert all(row.get("propagated") is False for row in target_rows if row.get("alternative_path_evidence"))
    assert len([row for row in impacts if row["best_path"]["node_ids"][-1] == "next"]) == 1


def test_file_neighbors_use_deterministic_relation_weighted_ranking(tmp_path: Path) -> None:
    with RuntimeStore(tmp_path / "graph.db") as graph:
        graph.rebuild(
            [
                GraphNode("seed", "Method", "seed", file_path="src/Seed.java"),
                GraphNode("strong", "Method", "strong", file_path="src/Strong.java"),
                GraphNode("weak", "File", "weak", file_path="src/Weak.java"),
            ],
            [
                GraphEdge("weak-edge", "seed", "weak", "CONTAINS", 1.0),
                GraphEdge("strong-edge", "seed", "strong", "CALLS_METHOD", 0.9),
            ],
        )
        ranked = graph.ranked_file_neighbors("src/Seed.java", limit=10)

    assert [row["file_path"] for row in ranked] == ["src/Strong.java", "src/Weak.java"]
    assert ranked[0]["strongest_score"] > ranked[1]["strongest_score"]
    assert ranked[0]["relation_types"] == ["CALLS_METHOD"]


def test_change_review_plan_is_progressive_and_deduplicated(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    store = WorkspaceStore(workspace)
    with RuntimeStore(store.graph_db_path) as graph:
        graph.rebuild(
            [
                GraphNode("endpoint", "Endpoint", "GET /orders", "api", "src/OrderController.java"),
                GraphNode("caller", "Method", "client", "web", "src/OrderClient.java"),
            ],
            [GraphEdge("call", "caller", "endpoint", "CALLS_METHOD", 1.0)],
        )

    first = build_change_review_plan(
        workspace,
        files=["src/OrderController.java"],
        detail_level="minimal",
        refresh=False,
    )
    second = build_change_review_plan(
        workspace,
        files=["src/OrderController.java"],
        detail_level="minimal",
        refresh=False,
    )

    assert first["workflow"] == "change_review_plan"
    assert first["summary"]["contract_change_count"] == 1
    assert first["summary"]["impacted_file_count"] >= 1
    assert first["invocation_budget"]["detail_level"] == "minimal"
    assert first["invocation_budget"]["stop_conditions"]
    assert second["cache"]["status"] == "hit"
    assert second["invocation_budget"]["fingerprint"] == first["invocation_budget"]["fingerprint"]


def test_git_cochange_is_independent_and_excludes_environment_errors(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    repo = root / "svc"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "src").mkdir()
    (repo / "src" / "A.java").write_text("class A {}\n", encoding="utf-8")
    (repo / "src" / "B.java").write_text("class B {}\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=repo, check=True)
    (repo / "src" / "A.java").write_text("class A { int v = 1; }\n", encoding="utf-8")
    (repo / "src" / "B.java").write_text("class B { int v = 1; }\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "second"], cwd=repo, check=True)
    workspace = _workspace(
        tmp_path,
        "services:\n  - name: svc\n    path: svc\n    type: spring-boot-service",
    )
    store = WorkspaceStore(workspace)
    with RuntimeStore(store.graph_db_path) as graph:
        graph.rebuild(
            [
                GraphNode("a", "Class", "A", "svc", "svc/src/A.java"),
                GraphNode("b", "Class", "B", "svc", "svc/src/B.java"),
            ],
            [GraphEdge("a-b", "a", "b", "CALLS_METHOD", 1.0)],
        )

    result = evaluate_git_cochange(workspace, max_commits=5, warmup_commits=1)

    assert result["status"] == "ready"
    assert result["ground_truth_mode"] == "walk_forward_same_commit_seed_excluded"
    assert result["summary"]["case_count"] == 2
    assert result["summary"]["mean_recall"] == 1.0
    assert result["summary"]["environment_error_count"] == 0
    assert all("src/" not in row["case_ref"] for row in result["cases"])


def test_walk_forward_cochange_never_trains_on_evaluation_commit() -> None:
    from memory_center.core.benchmark.cochange import _historical_predictions, _update_history

    history = {}
    popularity = {}
    _update_history(history, popularity, ["A.java", "B.java"], 0)

    assert _historical_predictions(history, "A.java", 8) == ["B.java"]
    assert "C.java" not in _historical_predictions(history, "A.java", 8)
    _update_history(history, popularity, ["A.java", "C.java"], 1)
    assert "C.java" in _historical_predictions(history, "A.java", 8)


def test_hashed_cochange_prior_only_reorders_existing_graph_candidates(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    store = WorkspaceStore(workspace)
    with RuntimeStore(store.graph_db_path) as graph:
        graph.rebuild(
            [
                GraphNode("a", "Class", "A", "svc", "svc/A.java"),
                GraphNode("b", "Class", "B", "svc", "svc/B.java"),
                GraphNode("c", "Class", "C", "svc", "svc/C.java"),
            ],
            [
                GraphEdge("a-b", "a", "b", "CALLS_METHOD", 1.0),
                GraphEdge("a-c", "a", "c", "CALLS_METHOD", 1.0),
            ],
        )
        from memory_center.core.benchmark.cochange import _path_ref

        graph.replace_cochange_priors(
            [
                {
                    "seed_ref": _path_ref("svc/A.java"),
                    "candidate_ref": _path_ref("svc/C.java"),
                    "support": 5,
                    "score": 1.0,
                }
            ],
            trained_at="2026-01-01T00:00:00Z",
        )
        ranked = graph.ranked_file_neighbors("svc/A.java", limit=5)
        with graph.connect() as conn:
            persisted = conn.execute("SELECT seed_ref,candidate_ref FROM cochange_priors").fetchone()

    assert ranked[0]["file_path"] == "svc/C.java"
    assert ranked[0]["cochange_support"] == 5
    assert "svc/" not in persisted["seed_ref"] + persisted["candidate_ref"]


def test_architecture_health_is_offline_inferred_projection(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    store = WorkspaceStore(workspace)
    with RuntimeStore(store.graph_db_path) as graph:
        graph.rebuild(
            [
                GraphNode("a", "Method", "a", "api", "api/src/A.java"),
                GraphNode("b", "Method", "b", "service", "service/src/B.java"),
                GraphNode("c", "Method", "c", "data", "data/src/C.java"),
            ],
            [
                GraphEdge("a-b", "a", "b", "CALLS_METHOD", 1.0),
                GraphEdge("b-c", "b", "c", "USES_DATA_RESOURCE", 0.6),
            ],
        )

    result = analyze_architecture_communities(workspace, limit=20)

    assert result["schema_version"] == 2
    assert result["kind"] == "architecture_communities"
    assert result["analysis_kind"] == "architecture_health"
    assert result["mode"] == "explicit_offline_aggregate"
    assert result["algorithm"]["status"] == "ready"
    assert result["evidence_level"] == "INFERRED"
    assert result["bridge_projects"]
    assert result["surprising_connections"]
