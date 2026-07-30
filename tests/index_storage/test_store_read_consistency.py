from __future__ import annotations

from pathlib import Path

from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.core.workspace.doctor import doctor


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


def test_runtime_only_index_is_not_exported_but_remains_readable(tmp_path: Path) -> None:
    store = _store(tmp_path)

    store.write_json("semantic-node-index.json", {"docs": [{"node_id": "Method:demo"}]})

    assert not (store.index_dir / "semantic-node-index.json").exists()
    assert store.read_json("semantic-node-index.json", {}) == {"docs": [{"node_id": "Method:demo"}]}


def test_runtime_only_export_cleanup_requires_canonical_sqlite_payload(tmp_path: Path) -> None:
    store = _store(tmp_path)
    path = store.index_dir / "java-symbol-index.json"
    path.write_text("[]", encoding="utf-8")

    assert store.cleanup_runtime_only_index_exports()["candidates"] == []
    assert path.exists()

    store.memory_backend().upsert_index("java-symbol-index.json", [])
    preview = store.cleanup_runtime_only_index_exports()
    assert preview["candidate_bytes"] == 2
    applied = store.cleanup_runtime_only_index_exports(apply=True)
    assert applied["removed"] == [{"name": "java-symbol-index.json", "bytes": 2}]
    assert not path.exists()


def test_doctor_uses_sqlite_for_runtime_only_index_health(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for name in (
        "file-index.json",
        "java-symbol-index.json",
        "api-index.json",
        "feign-index.json",
        "mq-index.json",
        "config-index.json",
        "service-topology.json",
        "semantic-node-index.json",
    ):
        store.memory_backend().upsert_index(name, {"docs": [{"node_id": "node"}]} if name == "semantic-node-index.json" else [])

    report = doctor(store.workspace_file)

    assert all(item["ok"] for item in report["checks"] if item["name"].startswith("index:"))
