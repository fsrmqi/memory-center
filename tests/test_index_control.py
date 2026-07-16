import json
from pathlib import Path

from memory_center.core.indexing.control_plane import index_control_status
from memory_center.core.indexing.reindex import reindex_workspace
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
    project = next(iter(store.read_json_prefer_backend("shard-manifest.json", {})["service_shards"]))
    reindex_workspace(load_workspace_config(workspace), store, projects=[project], parallel=False)
    generation = index_control_status(store)["active_generation"]
    manifest_path = store.index_dir / "generations" / generation / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["copy_on_write"] is True
    assert manifest["rebuilt_services"] == [project]


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
