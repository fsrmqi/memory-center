from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from filelock import Timeout
from typer.testing import CliRunner

import memory_center.core.indexing.reindex as indexer
from memory_center.cli.main import app
from memory_center.core.indexing import reindex_state
from memory_center.core.indexing.reindex_state import ReindexBusyError, workspace_reindex_lock, workspace_reindex_status
from memory_center.core.orchestrator import workspace_status
from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.core.workspace.config import load_workspace_config


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / ".memory-center" / "workspace.yaml"
    workspace.parent.mkdir(parents=True)
    workspace.write_text(yaml.safe_dump({"workspace": "coordination", "root": str(tmp_path), "services": []}), encoding="utf-8")
    return workspace


def test_reindex_lock_records_lifecycle_and_workspace_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = _workspace(tmp_path)
    store = WorkspaceStore(workspace)

    def fake_reindex(_config, _store, *, projects=None, paths=None, parallel=True, generation=""):
        assert projects == ["api"]
        assert paths == []
        assert parallel is False
        active = workspace_reindex_status(store)
        assert active["status"] == "running"
        return {"mode": "partial", "files": 1}

    monkeypatch.setattr(indexer, "_reindex_workspace_unlocked", fake_reindex)
    result = indexer.reindex_workspace(
        load_workspace_config(workspace),
        store,
        projects=["api"],
        paths=[],
        parallel=False,
    )

    assert result["mode"] == "partial"
    assert result["files"] == 1
    assert result["generation_gc"]["removed"] == 0
    status = workspace_reindex_status(store)
    assert status["status"] == "succeeded"
    assert status["lock_held"] is False
    assert status["project_count"] == 1
    assert status["last_success_at"]
    assert "reindex" in workspace_status(workspace, view="compact")


def test_reindex_lock_returns_conflict_when_writer_is_busy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = _workspace(tmp_path)
    store = WorkspaceStore(workspace)

    class BusyLock:
        def __init__(self, _path: str) -> None:
            pass

        def acquire(self, timeout: float = 0) -> None:
            raise Timeout("reindex.lock")

        def release(self) -> None:
            raise AssertionError("busy lock must not be released")

    monkeypatch.setattr(reindex_state, "FileLock", BusyLock)

    with pytest.raises(ReindexBusyError) as exc_info:
        with workspace_reindex_lock(store):
            raise AssertionError("unreachable")

    error = exc_info.value
    assert error.error_type == "conflict"
    assert error.diagnostics["status"] == "idle"
    assert "--lock-timeout" in error.suggested_action


def test_reindex_lock_marks_keyboard_interrupt_as_failed(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    store = WorkspaceStore(workspace)

    with pytest.raises(KeyboardInterrupt):
        with workspace_reindex_lock(store):
            raise KeyboardInterrupt

    status = workspace_reindex_status(store)
    assert status["status"] == "failed"
    assert status["lock_held"] is False
    assert status["error"] == "KeyboardInterrupt"


def test_reindex_cli_reports_lock_conflict_without_traceback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = _workspace(tmp_path)

    def fake_reindex(*_args, **_kwargs):
        raise ReindexBusyError({"status": "running", "started_at": "2026-01-01T00:00:00Z"}, 15.0)

    monkeypatch.setattr("memory_center.cli.commands.setup.reindex_workspace", fake_reindex)

    result = CliRunner().invoke(app, ["reindex", "--workspace", str(workspace), "--lock-timeout", "15"])

    assert result.exit_code == 1
    assert "[conflict] A workspace reindex is already running." in result.output
    assert "--lock-timeout" in result.output
    assert "Traceback" not in result.output
