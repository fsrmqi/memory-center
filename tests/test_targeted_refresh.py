from pathlib import Path

from memory_center.core.config import load_workspace_config
from memory_center.core.freshness.targeted_refresh import refresh_query_targets
from memory_center.core.graph import GraphStore
from memory_center.core.indexer import reindex_workspace
from memory_center.core.store import WorkspaceStore


def test_targeted_refresh_updates_only_changed_query_file(tmp_path: Path) -> None:
    from tests.fixtures import setup_demo_workspace

    workspace = setup_demo_workspace(tmp_path)
    store = WorkspaceStore(workspace)
    reindex_workspace(load_workspace_config(workspace), store, parallel=False)
    row = next(item for item in store.read_json_prefer_backend("file-index.json", []) if item["path"].endswith("ArticleFeignClient.java"))
    source = Path(row["abs_path"])
    source.write_text(source.read_text(encoding="utf-8") + "\n// HotRefreshMarker\n", encoding="utf-8")

    result = refresh_query_targets(workspace, "ArticleFeignClient", limit=4)

    assert result["refreshed"] is True
    assert row["path"] in result["files"]
    assert result["checked"] <= 4
    with GraphStore(store.graph_db_path) as graph:
        nodes = graph.find_nodes("ArticleFeignClient", types=["Class"], limit=5)
    assert any(node["name"] == "ArticleFeignClient" for node in nodes)
