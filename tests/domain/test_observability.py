from __future__ import annotations

from pathlib import Path

import pytest

from memory_center.core.observability.operations import OperationObserver, observe_operation
from memory_center.core.storage.workspace import WorkspaceStore


def _workspace(tmp_path: Path) -> Path:
    path = tmp_path / ".memory-center" / "workspace.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("workspace: test\nroot: ..\nservices: []\n", encoding="utf-8")
    return path


def test_operation_observer_records_safe_success_event(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    with OperationObserver(workspace, "lookup", tags={"workspace_path": "/private/demo", "parser": "regex"}) as observer:
        observer.set_result_count(3)

    event = WorkspaceStore(workspace).read_jsonl("operation-events.jsonl", 1)[0]
    assert event["operation"] == "lookup"
    assert event["outcome"] == "success"
    assert event["result_count"] == 3
    assert event["tags"]["workspace_path"] == "[redacted]"
    assert event["duration_ms"] >= 0


def test_observe_operation_records_failure_and_reraises(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)

    @observe_operation("explode", workspace_resolver=lambda args, kwargs: workspace)
    def explode() -> None:
        raise RuntimeError("secret details")

    with pytest.raises(RuntimeError):
        explode()
    event = WorkspaceStore(workspace).read_jsonl("operation-events.jsonl", 1)[0]
    assert event["outcome"] == "error"
    assert event["error_type"] == "RuntimeError"
    assert "secret details" not in str(event)
