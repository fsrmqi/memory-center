from __future__ import annotations

from pathlib import Path

from memory_center.core.storage.workspace import WorkspaceStore


def _store(tmp_path: Path) -> WorkspaceStore:
    workspace = tmp_path / ".memory-center" / "workspace.yaml"
    workspace.parent.mkdir(parents=True)
    workspace.write_text("workspace: test\nroot: ..\nservices: []\n", encoding="utf-8")
    return WorkspaceStore(workspace)


def test_runtime_json_ignores_changed_export_file(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.write_json("file-index.json", [{"path": "old.java"}])
    (store.index_dir / "file-index.json").write_text(
        '[{"path":"new.java"}]', encoding="utf-8"
    )
    assert store.read_json_prefer_backend("file-index.json", []) == [{"path": "old.java"}]


def test_runtime_jsonl_ignores_unrecorded_export_row(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.append_jsonl("events.jsonl", {"id": "one"})
    with (store.memory_dir / "events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write('{"id":"two"}\n')
    assert [row["id"] for row in store.read_jsonl_prefer_backend("events.jsonl", limit=10)] == ["one"]


def test_runtime_json_reads_empty_sqlite_payload(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.memory_backend().upsert_index("empty.json", [])

    assert store.read_json_prefer_backend("empty.json", ["default"]) == []


def test_runtime_json_returns_sqlite_value(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.write_json("data.json", {"ok": True})
    assert store.read_json_prefer_backend("data.json", {}) == {"ok": True}
