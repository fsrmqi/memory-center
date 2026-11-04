import threading
import time
from pathlib import Path

from memory_center.core.freshness.targeted_refresh import (
    compact_hot_refresh_overlay,
    hot_refresh_status,
    record_dirty_files,
    refresh_query_targets,
)
from memory_center.core.indexing.reindex import reindex_workspace
from memory_center.core.storage.runtime import RuntimeStore
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

    result = refresh_query_targets(workspace, "ArticleFeignClient", limit=4, synchronous=True)

    assert result["refreshed"] is True
    assert row["path"] in result["files"]
    assert result["checked"] <= 4
    second = refresh_query_targets(workspace, "ArticleFeignClient", limit=4, synchronous=True)
    assert second["refreshed"] is False
    with RuntimeStore(store.graph_db_path) as graph:
        nodes = graph.find_nodes("ArticleFeignClient", types=["Class"], limit=5)
        generation = graph.file_generation(row["path"])
    assert any(node["name"] == "ArticleFeignClient" for node in nodes)
    assert generation and generation["generation"] == 1
    assert generation["content_hash"]
    compacted = compact_hot_refresh_overlay(workspace)
    status = hot_refresh_status(workspace)
    assert compacted["generation_count"] == 1
    assert status["compacted_generation_count"] == 1


def test_query_refresh_is_scheduled_without_waiting_for_reindex(tmp_path: Path) -> None:
    from tests.fixtures import setup_demo_workspace

    workspace = setup_demo_workspace(tmp_path)
    result = refresh_query_targets(workspace, "ArticleFeignClient", limit=4)

    assert result["scheduled"] is True
    assert result["mode"] == "targeted_overlay_async"


def test_partial_reindex_reports_stage_timings_and_aggregate_governance(tmp_path: Path) -> None:
    from memory_center.core.retrieval.planner import scoped_refresh_performance_status
    from tests.fixtures import setup_demo_workspace

    workspace = setup_demo_workspace(tmp_path)
    store = WorkspaceStore(workspace)
    row = store.read_json_prefer_backend("file-index.json", [])[0]
    result = reindex_workspace(load_workspace_config(workspace), store, paths=[row["path"]], parallel=False)

    assert result["timing_ms"]["total"] >= result["timing_ms"]["pipeline_total"]
    assert {
        "load_indexes",
        "scan_scope",
        "parse_and_merge",
        "persist_indexes",
        "graph_update",
        "semantic_update",
        "retrieval_update",
        "generation_publish",
        "generation_inherit",
        "generation_service_payloads",
        "generation_graph_shards",
        "generation_shared_shards",
        "assertion_projection",
    }.issubset(result["timing_ms"])
    assert result["refresh_performance"]["status"] in {"healthy", "warning"}
    status = scoped_refresh_performance_status(workspace)
    assert status["samples"] == 1
    assert "paths" not in status["latest"]


def test_exact_path_refresh_does_not_walk_whole_service(tmp_path: Path, monkeypatch) -> None:
    import memory_center.core.indexing.reindex as reindex_module
    from tests.fixtures import setup_demo_workspace

    workspace = setup_demo_workspace(tmp_path)
    store = WorkspaceStore(workspace)
    row = store.read_json_prefer_backend("file-index.json", [])[0]

    def forbidden_walk(_root: Path):
        raise AssertionError("exact path refresh must not scan the whole service")

    monkeypatch.setattr(reindex_module, "walk_project", forbidden_walk)
    result = reindex_workspace(load_workspace_config(workspace), store, paths=[row["path"]], parallel=False)

    assert result["scanned_files"] == 1


def test_async_refresh_processes_requests_queued_while_worker_is_active(tmp_path: Path, monkeypatch) -> None:
    import memory_center.core.freshness.targeted_refresh as refresh_module
    from tests.fixtures import setup_demo_workspace

    workspace = setup_demo_workspace(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    processed: list[str] = []

    def controlled_refresh(store, query: str, limit: int):
        processed.append(query)
        if query == "first":
            entered.set()
            assert release.wait(timeout=3)
        return {"checked": 0, "refreshed": False, "files": [], "elapsed_ms": 0.0}

    monkeypatch.setattr(refresh_module, "_refresh_query_targets", controlled_refresh)
    refresh_query_targets(workspace, "first", limit=4)
    assert entered.wait(timeout=3)
    queued = refresh_query_targets(workspace, "second", limit=4)
    assert queued["coalesced"] is True
    release.set()

    deadline = time.monotonic() + 3
    while "second" not in processed and time.monotonic() < deadline:
        time.sleep(0.01)
    assert processed == ["first", "second"]


def test_targeted_refresh_preserves_controller_endpoint_facts(tmp_path: Path) -> None:
    from tests.fixtures import setup_demo_workspace

    workspace = setup_demo_workspace(tmp_path)
    store = WorkspaceStore(workspace)
    api = store.read_json_prefer_backend("api-index.json", [])[0]
    row = next(item for item in store.read_json_prefer_backend("file-index.json", []) if item["path"] == api["file"])
    source = Path(row["abs_path"])

    with RuntimeStore(store.graph_db_path) as graph:
        with graph.connect() as conn:
            before = conn.execute("SELECT COUNT(*) FROM nodes WHERE type='Endpoint' AND file_path=?", (api["file"],)).fetchone()[0]

    source.write_text(source.read_text(encoding="utf-8") + "\n// RefreshEndpointFact\n", encoding="utf-8")
    result = refresh_query_targets(workspace, api["controller"], limit=4, synchronous=True)

    with RuntimeStore(store.graph_db_path) as graph:
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
    added_result = refresh_query_targets(workspace, "NewRefreshController", limit=4, synchronous=True)
    assert added_result["refreshed"] is True
    assert any(item["path"] == added_path for item in store.read_json_prefer_backend("file-index.json", []))

    added.unlink()
    record_dirty_files(workspace, [added_path])
    deleted_result = refresh_query_targets(workspace, "NewRefreshController", limit=4, synchronous=True)
    assert deleted_result["refreshed"] is True
    assert not any(item["path"] == added_path for item in store.read_json_prefer_backend("file-index.json", []))
