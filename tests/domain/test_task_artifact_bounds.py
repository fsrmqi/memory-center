from pathlib import Path

from memory_center.core.orchestrator import sync as sync_module
from memory_center.core.tasks.artifacts import (
    TASK_ARTIFACT_EXCERPT_BYTES,
    TASK_ARTIFACT_WRITE_MAX_BYTES,
    archive_task_space,
    create_task_space,
    get_task_artifact,
    get_task_evidence_chunk,
    resolve_task_space,
    task_space_health,
    update_task_artifact,
    write_task_evidence_chunk,
)


def _workspace(tmp_path: Path) -> Path:
    from tests.fixtures import copy_demo_workspace

    return copy_demo_workspace(tmp_path)


def test_task_artifact_excerpt_keeps_default_full_read_and_reports_truncation(tmp_path: Path):
    workspace = _workspace(tmp_path)
    task = create_task_space(workspace, title="超大任务工件")
    context_path = Path(task["path"]) / "context.md"
    content = "x" * (TASK_ARTIFACT_EXCERPT_BYTES + 100)
    context_path.write_text(content, encoding="utf-8")

    excerpt = get_task_artifact(workspace, task["task_id"], "context", max_bytes=128)
    full = get_task_artifact(workspace, task["task_id"], "context")

    assert excerpt["truncated"] is True
    assert excerpt["total_bytes"] == len(content.encode("utf-8"))
    assert len(excerpt["content"]) == 128
    assert full["truncated"] is False
    assert full["content"] == content


def test_task_resolution_and_health_use_bounded_large_artifact_reads(tmp_path: Path):
    workspace = _workspace(tmp_path)
    task = create_task_space(workspace, title="链路分析任务", intent="处理链路分析")
    context_path = Path(task["path"]) / "context.md"
    context_path.write_text("链路分析\n" + "x" * (TASK_ARTIFACT_EXCERPT_BYTES * 5), encoding="utf-8")

    resolved = resolve_task_space(workspace, intent="继续处理链路分析", create_if_missing=False, score_threshold=1)
    health = task_space_health(workspace, task["task_id"])

    assert resolved["task_id"] == task["task_id"]
    assert health["artifact_summary"]["context"]["truncated"] is True
    assert any(issue["code"] == "oversized_context" for issue in health["issues"])


def test_sync_preserves_oversized_artifact_without_merging(tmp_path: Path):
    workspace = _workspace(tmp_path)
    task = create_task_space(workspace, title="自动同步超大工件")
    context_path = Path(task["path"]) / "context.md"
    original = "x" * (sync_module.TASK_SYNC_EXISTING_ARTIFACT_MAX_BYTES + 1)
    context_path.write_text(original, encoding="utf-8")

    skipped = sync_module._sync_task_artifact_section(
        workspace,
        task["task_id"],
        "context",
        "Sniff Context",
        "new context",
        source="test",
    )

    assert skipped is True
    assert context_path.read_text(encoding="utf-8") == original


def test_direct_task_update_rejects_oversized_merge_without_reading(tmp_path: Path):
    workspace = _workspace(tmp_path)
    task = create_task_space(workspace, title="直接更新超大工件")
    plan_path = Path(task["path"]) / "plan.md"
    plan_path.write_text("x" * (TASK_ARTIFACT_WRITE_MAX_BYTES + 1), encoding="utf-8")

    result = update_task_artifact(workspace, task["task_id"], "plan", "new plan")

    assert result["updated"] is False
    assert result["reason"] == "artifact_too_large_for_merge"
    assert plan_path.stat().st_size > TASK_ARTIFACT_WRITE_MAX_BYTES


def test_large_task_update_is_content_addressed_evidence(tmp_path: Path):
    workspace = _workspace(tmp_path)
    task = create_task_space(workspace, title="证据分块")
    payload = "证据" * (40 * 1024)

    result = update_task_artifact(workspace, task["task_id"], "context", payload)
    duplicate = write_task_evidence_chunk(workspace, task["task_id"], payload)
    loaded = get_task_evidence_chunk(workspace, task["task_id"], result["evidence"]["ref"], max_bytes=32)

    assert result["updated"] is True
    assert result["evidence"]["hash"] == duplicate["hash"]
    assert duplicate["deduplicated"] is True
    assert loaded["found"] is True
    assert loaded["truncated"] is True


def test_concurrent_task_artifact_appends_do_not_lose_writes(tmp_path: Path, monkeypatch):
    """读-改-写整体持锁：并发 append 必须都落盘，不能后写者覆盖先写者。"""
    import threading
    import time

    from memory_center.core.tasks import artifacts as artifacts_module

    workspace = _workspace(tmp_path)
    task = create_task_space(workspace, title="并发追加工件")
    original_merge = artifacts_module._merge_append_only_artifact

    def slow_merge(existing, content, key):
        # 拉长合并窗口：合并若在锁外，两个线程会基于同一份旧内容合并后互相覆盖。
        time.sleep(0.05)
        return original_merge(existing, content, key)

    monkeypatch.setattr(artifacts_module, "_merge_append_only_artifact", slow_merge)
    errors: list[BaseException] = []

    def append(section: str) -> None:
        try:
            result = update_task_artifact(workspace, task["task_id"], "context", f"## {section}\n\n{section} body")
            assert result["updated"] is True
        except BaseException as exc:  # noqa: BLE001 - re-raised via `errors` below
            errors.append(exc)

    threads = [threading.Thread(target=append, args=(name,)) for name in ("alpha", "beta")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    content = (Path(task["path"]) / "context.md").read_text(encoding="utf-8")
    assert "## alpha" in content
    assert "## beta" in content


def test_workspace_artifact_writers_share_one_lock(tmp_path: Path, monkeypatch):
    """change-log 追加/压缩与通用工件更新必须共用 artifact_lock_file。"""
    from filelock import FileLock as RealFileLock

    from memory_center.core.storage.workspace import WorkspaceStore
    from memory_center.core.tasks import artifacts as artifacts_module

    workspace = _workspace(tmp_path)
    store = WorkspaceStore(workspace)
    recorded: list[str] = []

    class RecordingLock:
        def __init__(self, lock_file, *args, **kwargs):
            recorded.append(str(lock_file))
            self._inner = RealFileLock(lock_file, *args, **kwargs)

        def __enter__(self):
            return self._inner.__enter__()

        def __exit__(self, *exc):
            return self._inner.__exit__(*exc)

    monkeypatch.setattr(artifacts_module, "FileLock", RecordingLock)

    artifacts_module.append_change_log(workspace, "统一锁回归条目")
    artifacts_module.update_artifact(workspace, "change_log", "## 统一锁回归\n\nbody")
    artifacts_module.compact_change_log(workspace, keep_recent=1)

    assert recorded, "workspace artifact writers must take a lock"
    assert set(recorded) == {str(store.artifact_lock_file)}


def test_rearchiving_same_slug_preserves_previous_archive(tmp_path: Path):
    """同名任务重建后再归档：旧归档必须被保留，不能被 rmtree 静默销毁。"""
    workspace = _workspace(tmp_path)
    first = create_task_space(workspace, title="同名任务")
    update_task_artifact(workspace, first["task_id"], "context", "## First\n\nfirst archive body")
    archived_first = archive_task_space(workspace, first["task_id"], reason="first")
    assert archived_first["preserved_archives"] == []
    assert "first archive body" in (Path(archived_first["path"]) / "context.md").read_text(encoding="utf-8")

    second = create_task_space(workspace, title="同名任务")
    assert second["task_id"] == first["task_id"]
    update_task_artifact(workspace, second["task_id"], "context", "## Second\n\nsecond archive body")
    archived_second = archive_task_space(workspace, second["task_id"], reason="second")

    assert archived_second["preserved_archives"], "同名归档冲突时必须保留旧归档"
    preserved = Path(archived_second["preserved_archives"][0]["path"])
    assert preserved.exists()
    assert "first archive body" in (preserved / "context.md").read_text(encoding="utf-8")
    # canonical 归档路径仍是 task_id，归档任务依旧可按 id 解析
    assert Path(archived_second["path"]).name == first["task_id"]
    assert "second archive body" in (Path(archived_second["path"]) / "context.md").read_text(encoding="utf-8")
