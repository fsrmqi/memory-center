import json
from pathlib import Path

from memory_center.core.indexing.control_plane import index_control_status
from memory_center.core.indexing.reindex import _affected_shard_projects, _graph_scope_path_filters, reindex_workspace
from memory_center.core.indexing.shards import load_service_shard, service_shard_graph_path
from memory_center.core.orchestrator.query import memory_query_hybrid, memory_search_code
from memory_center.core.retrieval.cross_service import (
    evaluate_cross_shard_replay,
    query_cross_service_shards,
    route_cross_service_shards,
)
from memory_center.core.retrieval.cross_service_fusion import evaluate_cross_shard_fusion, fuse_cross_shard_result
from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.core.workspace.config import load_workspace_config


def test_reindex_publishes_active_generation_and_shard_manifest(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    store = WorkspaceStore(workspace)
    reindex_workspace(load_workspace_config(workspace), store, parallel=False)

    control = index_control_status(store)
    manifest = store.read_json_prefer_backend("shard-manifest.json", {})
    assert control["status"] == "ready"
    assert control["active_generation"]
    assert manifest["generation"] == control["active_generation"]
    assert manifest["service_shards"]
    project = next(iter(manifest["service_shards"]))
    shard = load_service_shard(store, control["active_generation"], project)
    assert shard and shard["files"]
    assert service_shard_graph_path(store, control["active_generation"], project)


def test_project_queries_prefer_physical_service_shards(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    store = WorkspaceStore(workspace)
    reindex_workspace(load_workspace_config(workspace), store, parallel=False)
    project = next(iter(store.read_json_prefer_backend("shard-manifest.json", {})["service_shards"]))

    code = memory_search_code(workspace, "article", project=project)
    query = memory_query_hybrid(workspace, "article", project=project)

    assert code["index_source"] == "service_shard"
    assert query["index_source"] == "service_graph_shard"


def test_partial_reindex_uses_copy_on_write_service_shards(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    store = WorkspaceStore(workspace)
    reindex_workspace(load_workspace_config(workspace), store, parallel=False)
    first_generation = index_control_status(store)["active_generation"]
    project = next(iter(store.read_json_prefer_backend("shard-manifest.json", {})["service_shards"]))
    reindex_workspace(load_workspace_config(workspace), store, projects=[project], parallel=False)
    generation = index_control_status(store)["active_generation"]
    manifest_path = store.index_dir / "generations" / generation / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["copy_on_write"] is True
    assert manifest["rebuilt_services"] == [project]
    rebuilt = service_shard_graph_path(store, generation, project)
    previous_rebuilt = service_shard_graph_path(store, first_generation, project)
    assert rebuilt and previous_rebuilt
    assert rebuilt.stat().st_ino != previous_rebuilt.stat().st_ino
    unchanged = next(name for name in manifest["services"] if name != project)
    current_unchanged = service_shard_graph_path(store, generation, unchanged)
    previous_unchanged = service_shard_graph_path(store, first_generation, unchanged)
    assert current_unchanged and previous_unchanged
    assert current_unchanged.stat().st_ino == previous_unchanged.stat().st_ino


def test_absolute_path_filter_rebuilds_only_its_service_shard() -> None:
    file_index = [
        {
            "project": "order-service",
            "path": "src/main/java/OrderController.java",
            "abs_path": "/work/order/src/main/java/OrderController.java",
        },
        {
            "project": "user-service",
            "path": "src/main/java/UserController.java",
            "abs_path": "/work/user/src/main/java/UserController.java",
        },
    ]

    assert _affected_shard_projects(
        file_index,
        set(),
        ["/work/order/src/main/java/OrderController.java"],
    ) == {"order-service"}
    assert _graph_scope_path_filters(
        file_index,
        ["/work/order/src/main/java/OrderController.java"],
    ) == ["src/main/java/OrderController.java"]


def test_graph_store_indexes_file_path_for_targeted_refresh(tmp_path: Path) -> None:
    store = WorkspaceStore(tmp_path / ".memory-center" / "workspace.yaml")
    with store.memory_backend() as graph:
        plan = graph.connect().execute(
            "EXPLAIN QUERY PLAN SELECT id FROM nodes WHERE file_path = ?",
            ("src/main/java/OrderController.java",),
        ).fetchall()

    assert any("idx_nodes_file_path" in str(row[3]) for row in plan)


def test_project_subgraph_uses_project_join_without_parameter_blowup(tmp_path: Path) -> None:
    store = WorkspaceStore(tmp_path / ".memory-center" / "workspace.yaml")
    with store.memory_backend() as graph:
        plan = graph.connect().execute(
            """
            EXPLAIN QUERY PLAN
            SELECT edge.id
            FROM edges AS edge
            JOIN nodes AS source_node ON source_node.id = edge.source_id
            JOIN nodes AS target_node ON target_node.id = edge.target_id
            WHERE source_node.project = ? AND target_node.project = ?
            """,
            ("order-service", "order-service"),
        ).fetchall()

    assert any("idx_nodes_project" in str(row[3]) for row in plan)


def test_cross_service_router_uses_contracts_topology_and_parallel_shards(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    store = WorkspaceStore(workspace)
    reindex_workspace(load_workspace_config(workspace), store, parallel=False)

    route = route_cross_service_shards(workspace, "ArticleFeignClient 全链路", tier="standard")
    evidence = query_cross_service_shards(workspace, "ArticleFeignClient", route)
    gate = evaluate_cross_shard_replay(workspace, ["ArticleFeignClient", "article-service"], tier="fast")

    assert route["available"] is True
    assert "common-api" in route["selected_projects"]
    assert evidence["source"] == "parallel_service_shards"
    assert evidence["queried_projects"]
    assert gate["samples"] == 2


def test_cross_shard_fusion_deduplicates_evidence_and_checks_generation(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    store = WorkspaceStore(workspace)
    reindex_workspace(load_workspace_config(workspace), store, parallel=False)
    route = route_cross_service_shards(workspace, "ArticleFeignClient", tier="standard")
    evidence = query_cross_service_shards(workspace, "ArticleFeignClient", route)
    fused = fuse_cross_shard_result(workspace, "ArticleFeignClient", {"matches": evidence["matches"]}, route, evidence)
    gate = evaluate_cross_shard_fusion(
        workspace,
        [{"query": "ArticleFeignClient", "expected_projects": ["common-api"]}],
    )

    assert fused["generation"]["consistent"] is True
    assert fused["normalized_matches"]
    assert fused["conclusions"]
    assert gate["passed"] is True
