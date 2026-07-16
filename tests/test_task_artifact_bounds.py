from pathlib import Path

from memory_center.core.artifacts import (
    TASK_ARTIFACT_EXCERPT_BYTES,
    TASK_ARTIFACT_WRITE_MAX_BYTES,
    create_task_space,
    get_task_artifact,
    get_task_evidence_chunk,
    resolve_task_space,
    task_space_health,
    update_task_artifact,
    write_task_evidence_chunk,
)
from memory_center.core.orchestrator import sync as sync_module


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
