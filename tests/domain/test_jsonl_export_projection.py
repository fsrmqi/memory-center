"""SQLite-first JSONL projection recovery tests."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from memory_center.core.storage.workspace import WorkspaceStore


def test_jsonl_export_status_tracks_authoritative_append(demo_workspace: Path) -> None:
    store = WorkspaceStore(demo_workspace)
    store.append_jsonl("projection-test.jsonl", {"event_type": "first"})
    status = store.jsonl_export_status("projection-test.jsonl")
    assert status["dirty"] is False
    assert status["needs_sync"] is False
    assert status["last_record_id"] == status["latest_record_id"]


def test_dirty_jsonl_export_rebuilds_from_sqlite(demo_workspace: Path) -> None:
    store = WorkspaceStore(demo_workspace)
    collection = "projection-rebuild.jsonl"
    store.append_jsonl(collection, {"event_type": "first"})
    store.append_jsonl(collection, {"event_type": "second"})
    path = store.memory_dir / collection
    path.write_text('{"corrupt":true}\n', encoding="utf-8")
    state = store.jsonl_export_status(collection)
    store.memory_backend().set_jsonl_export_state(
        collection,
        last_record_id=state["last_record_id"],
        dirty=True,
        updated_at="2026-01-01T00:00:00+00:00",
    )

    synced = store.sync_jsonl_export(collection)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert synced["rebuild"] is True
    assert [row["event_type"] for row in rows] == ["first", "second"]
    assert store.jsonl_export_status(collection)["needs_sync"] is False


def test_backend_consistency_reports_and_repairs_projection(demo_workspace: Path) -> None:
    from memory_center.application.admin import backend_consistency

    store = WorkspaceStore(demo_workspace)
    collection = "projection-consistency.jsonl"
    store.append_jsonl(collection, {"event_type": "first"})
    state = store.jsonl_export_status(collection)
    store.memory_backend().set_jsonl_export_state(
        collection, last_record_id=state["last_record_id"], dirty=True, updated_at="2026-01-01T00:00:00+00:00"
    )

    report = backend_consistency(str(demo_workspace))
    assert report["jsonl_projection"]["status"] == "attention"
    repaired = backend_consistency(str(demo_workspace), repair_exports=True, apply=True)
    assert repaired["jsonl_projection"]["applied"] is True
    assert repaired["jsonl_projection"]["status"] == "pass"


def test_concurrent_append_batch_prune_and_rebuild_is_idempotent(demo_workspace: Path) -> None:
    collection = "projection-stress.jsonl"
    def append(index: int) -> None:
        WorkspaceStore(demo_workspace).append_jsonl(collection, {"event_type": f"single-{index}"})
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(append, range(16)))
    store = WorkspaceStore(demo_workspace)
    store.append_jsonl_batch(collection, [{"event_type": f"batch-{index}"} for index in range(4)])
    store.prune_jsonl(collection, created_before=__import__("datetime").datetime(2000, 1, 1, tzinfo=__import__("datetime").timezone.utc), max_records=100)
    first = store.sync_jsonl_export(collection)
    second = store.sync_jsonl_export(collection)
    rows = [json.loads(line) for line in (store.memory_dir / collection).read_text(encoding="utf-8").splitlines()]
    assert first["rebuild"] is True
    assert second["exported"] == 0
    assert len(rows) == 20
    assert store.jsonl_export_status(collection)["needs_sync"] is False


def test_torn_tail_rebuilds_instead_of_appending_after_half_line(demo_workspace: Path) -> None:
    """进程在"SQLite 已提交、JSONL 只写了一半"时被杀：同步必须重建，不能接在半行后面。"""
    store = WorkspaceStore(demo_workspace)
    collection = "projection-torn.jsonl"
    store.append_jsonl(collection, {"event_type": "first"})
    store.append_jsonl(collection, {"event_type": "second"})
    # 模拟强杀：权威记录已提交，导出只落了半行，水位仍停在上一笔。
    store.memory_backend().append_record(collection, {"event_type": "third"})
    path = store.memory_dir / collection
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"event_type": "thi')
    assert store.jsonl_export_status(collection)["needs_sync"] is True
    # 半条记录不能被读取方当成事实。
    assert [row.get("event_type") for row in store.read_jsonl(collection, limit=10)] == ["first", "second"]

    first = store.sync_jsonl_export(collection)
    second = store.sync_jsonl_export(collection)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert first["rebuild"] is True
    assert second["exported"] == 0
    assert [row["event_type"] for row in rows] == ["first", "second", "third"]
    assert path.read_text(encoding="utf-8").endswith("\n")
    assert store.jsonl_export_status(collection)["needs_sync"] is False
