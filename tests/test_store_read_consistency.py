from __future__ import annotations

import json
from pathlib import Path

from memory_center.core.store import WorkspaceStore


def _store(tmp_path: Path) -> WorkspaceStore:
    workspace = tmp_path / ".memory-center" / "workspace.yaml"
    workspace.parent.mkdir(parents=True)
    workspace.write_text("workspace: test\nroot: ..\nservices: []\n", encoding="utf-8")
    return WorkspaceStore(workspace)


def test_observed_json_prefers_newer_file_over_stale_backend(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.write_json("file-index.json", [{"path": "old.java"}])
    (store.index_dir / "file-index.json").write_text(
        json.dumps([{"path": "new.java"}]), encoding="utf-8"
    )

    result = store.read_json_observed("file-index.json", [])

    assert result.value == [{"path": "new.java"}]
    assert result.source == "file"
    assert result.fallback_used is True
    assert result.fallback_reason == "backend_stale"
    assert result.consistency_status == "diverged"


def test_observed_jsonl_prefers_file_when_backend_is_partial(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.append_jsonl("events.jsonl", {"id": "one"})
    with (store.memory_dir / "events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"id": "two", "created_at": "2099-01-01T00:00:00+00:00"}) + "\n")

    result = store.read_jsonl_observed("events.jsonl", limit=10)

    assert [row["id"] for row in result.value] == ["one", "two"]
    assert result.source == "file"
    assert result.fallback_reason == "backend_partial"
    assert result.consistency_status == "diverged"


def test_observed_json_accepts_legal_empty_backend_payload(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.memory_backend().upsert_index("empty.json", [])

    result = store.read_json_observed("empty.json", ["default"])

    assert result.value == []
    assert result.source == "backend"
    assert result.fallback_used is False
    assert result.consistency_status == "backend_only"


def test_legacy_read_returns_value_only(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.write_json("data.json", {"ok": True})
    assert store.read_json_prefer_backend("data.json", {}) == {"ok": True}
