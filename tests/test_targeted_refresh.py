from pathlib import Path

from memory_center.core.freshness.targeted_refresh import (
    compact_hot_refresh_overlay,
    hot_refresh_status,
    record_dirty_files,
    refresh_query_targets,
)
from memory_center.core.indexing.reindex import reindex_workspace
from memory_center.core.storage.graph import GraphStore
from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.core.workspace.config import load_workspace_config


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
    second = refresh_query_targets(workspace, "ArticleFeignClient", limit=4)
    assert second["refreshed"] is False
    with GraphStore(store.graph_db_path) as graph:
        nodes = graph.find_nodes("ArticleFeignClient", types=["Class"], limit=5)
        generation = graph.file_generation(row["path"])
    assert any(node["name"] == "ArticleFeignClient" for node in nodes)
    assert generation and generation["generation"] == 1
    assert generation["content_hash"]
    compacted = compact_hot_refresh_overlay(workspace)
    status = hot_refresh_status(workspace)
    assert compacted["generation_count"] == 1
    assert status["compacted_generation_count"] == 1


def test_targeted_refresh_preserves_controller_endpoint_facts(tmp_path: Path) -> None:
    from tests.fixtures import setup_demo_workspace

    workspace = setup_demo_workspace(tmp_path)
    store = WorkspaceStore(workspace)
    api = store.read_json_prefer_backend("api-index.json", [])[0]
    row = next(item for item in store.read_json_prefer_backend("file-index.json", []) if item["path"] == api["file"])
    source = Path(row["abs_path"])

    with GraphStore(store.graph_db_path) as graph:
        with graph.connect() as conn:
            before = conn.execute("SELECT COUNT(*) FROM nodes WHERE type='Endpoint' AND file_path=?", (api["file"],)).fetchone()[0]

    source.write_text(source.read_text(encoding="utf-8") + "\n// RefreshEndpointFact\n", encoding="utf-8")
    result = refresh_query_targets(workspace, api["controller"], limit=4)

    with GraphStore(store.graph_db_path) as graph:
        with graph.connect() as conn:
            after = conn.execute("SELECT COUNT(*) FROM nodes WHERE type='Endpoint' AND file_path=?", (api["file"],)).fetchone()[0]
    assert result["refreshed"] is True
    assert before > 0
    assert after == before


def test_targeted_refresh_reconciles_added_and_deleted_files(tmp_path: Path) -> None:
    from tests.fixtures import setup_demo_workspace

    workspace = setup_demo_workspace(tmp_path)
    store = WorkspaceStore(workspace)
    root = load_workspace_config(workspace).root_path
    added = root / "article-service/src/main/java/com/example/article/NewRefreshController.java"
    added.write_text("package com.example.article;\npublic class NewRefreshController {}\n", encoding="utf-8")
    added_path = added.relative_to(root).as_posix()

    record_dirty_files(workspace, [added_path])
    added_result = refresh_query_targets(workspace, "NewRefreshController", limit=4)
    assert added_result["refreshed"] is True
    assert any(item["path"] == added_path for item in store.read_json_prefer_backend("file-index.json", []))

    added.unlink()
    record_dirty_files(workspace, [added_path])
    deleted_result = refresh_query_targets(workspace, "NewRefreshController", limit=4)
    assert deleted_result["refreshed"] is True
    assert not any(item["path"] == added_path for item in store.read_json_prefer_backend("file-index.json", []))
