from pathlib import Path

from memory_center.core.config import load_workspace_config
from memory_center.core.index_control import index_control_status
from memory_center.core.indexer import reindex_workspace
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
