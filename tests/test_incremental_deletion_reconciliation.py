from __future__ import annotations

from pathlib import Path

from memory_center.core.config import load_workspace_config
from memory_center.core.indexer import reindex_workspace
from memory_center.core.indexing.incremental import ChangedFile, IncrementalIndexer
from memory_center.core.storage.unified import UnifiedStore
from memory_center.core.store import WorkspaceStore


def _workspace(tmp_path: Path) -> tuple[Path, Path, WorkspaceStore]:
    root = tmp_path / "repo"
    java = root / "svc" / "src" / "main" / "java" / "Demo.java"
    java.parent.mkdir(parents=True)
    java.write_text("package demo; public class Demo { public void run() {} }", encoding="utf-8")
    workspace = root / ".memory-center" / "workspace.yaml"
    workspace.parent.mkdir(parents=True)
    workspace.write_text(
        "workspace: test\nroot: ..\nservices:\n  - name: svc\n    path: svc\n",
        encoding="utf-8",
    )
    store = WorkspaceStore(workspace)
    reindex_workspace(load_workspace_config(workspace), store)
    return workspace, java, store


def test_incremental_delete_removes_deterministic_index_rows(tmp_path: Path) -> None:
    workspace, java, store = _workspace(tmp_path)
    logical = store.read_json_prefer_backend("file-index.json", [])[0]["path"]
    java.unlink()
    unified = UnifiedStore(store.graph_db_path)
    try:
        indexer = IncrementalIndexer(unified, workspace.parent.parent, workspace)
        indexer.detect_changes = lambda since="HEAD": {
            "added": [], "modified": [], "deleted": [ChangedFile(logical, "D")], "renamed": [],
        }
        result = indexer.incremental_reindex(parse_fn=None)
    finally:
        unified.close()

    assert result["reindexed"] is True
    assert store.read_json_prefer_backend("file-index.json", []) == []
    assert store.read_json_prefer_backend("java-symbol-index.json", []) == []


def test_renamed_change_tracks_old_and_new_paths() -> None:
    change = ChangedFile("src/New.java", "R", previous_path="src/Old.java")
    assert change.previous_path == "src/Old.java"
