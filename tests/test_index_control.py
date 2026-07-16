import json
from pathlib import Path

from memory_center.core.config import load_workspace_config
from memory_center.core.index_control import index_control_status
from memory_center.core.indexer import reindex_workspace
from memory_center.core.index_shards import load_service_shard, service_shard_graph_path
from memory_center.core.orchestrator.query import memory_query_hybrid, memory_search_code
from memory_center.core.store import WorkspaceStore


def test_reindex_publishes_active_generation_and_shard_manifest(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    store = WorkspaceStore(workspace)
    result = reindex_workspace(load_workspace_config(workspace), store, parallel=False)

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
