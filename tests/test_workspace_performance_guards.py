from pathlib import Path

from memory_center.core.indexing.reindex import reindex_workspace
from memory_center.core.orchestrator import workspace_sniff, workspace_status, workspace_sync_sniff_to_artifacts
from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.core.tasks.artifacts import create_task_space
from memory_center.core.workspace.config import load_workspace_config


def _workspace(tmp_path: Path) -> Path:
    from tests.fixtures import setup_demo_workspace

    return setup_demo_workspace(tmp_path)


def test_status_uses_index_summary_without_reading_large_indexes(tmp_path: Path, monkeypatch) -> None:
    workspace = _workspace(tmp_path)
    store = WorkspaceStore(workspace)
    reindex_workspace(load_workspace_config(workspace), store, parallel=False)
    original = store.read_json_prefer_backend

    def guarded(name: str, default):
        if name in {"java-symbol-index.json", "semantic-node-index.json"}:
            raise AssertionError(f"status must not load {name}")
        return original(name, default)

    monkeypatch.setattr(WorkspaceStore, "read_json_prefer_backend", lambda self, name, default: guarded(name, default))
    result = workspace_status(workspace, view="compact")

    assert result["index_counts"]["symbols"] > 0
    assert result["semantic_index"]["summary_source"] == "index-summary.json"


def test_sniff_reports_cache_and_retrieval_performance(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    first = workspace_sniff(workspace, "ArticleFeignClient 调用链", view="compact", budget="small")
    second = workspace_sniff(workspace, "ArticleFeignClient 调用链", view="compact", budget="small")

    assert first["performance"]["cache_hit"] is False
    assert second["performance"]["cache_hit"] is True
    assert first["performance"]["retrieval_mode"] in {"symbol_rank", "graph_fts", "path_fallback"}
    assert "total_ms" in first["performance"]


def test_sync_reuses_supplied_sniff_without_second_query(tmp_path: Path, monkeypatch) -> None:
    workspace = _workspace(tmp_path)
    task = create_task_space(workspace, title="复用 sniff 任务")
    sniff = workspace_sniff(workspace, "ArticleFeignClient", view="compact")

    import memory_center.core.orchestrator.workspace_ops as workspace_module

    monkeypatch.setattr(workspace_module, "workspace_sniff", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must reuse sniff")))
    result = workspace_sync_sniff_to_artifacts(workspace, "ArticleFeignClient", task_id=task["task_id"], sniff_result=sniff)

    assert result["synced"] is True
    assert result["sniff_reused"] is True
