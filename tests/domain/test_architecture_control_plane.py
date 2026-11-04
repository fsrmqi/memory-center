from pathlib import Path

from memory_center.core.freshness.invalidation import build_invalidation_plan
from memory_center.core.freshness.watcher import trigger_incremental_reindex
from memory_center.core.indexing.control_plane import index_control_status, rollback_generation
from memory_center.core.indexing.reindex import reindex_workspace
from memory_center.core.retrieval.planner import QueryPlanner
from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.core.tasks.artifacts import (
    create_task_space,
    get_task_evidence_chunk,
    record_task_decision,
    task_evidence_gc,
    update_task_artifact,
    write_task_evidence_chunk,
)
from memory_center.core.workspace.config import load_workspace_config


def _workspace(tmp_path: Path) -> Path:
    from tests.fixtures import copy_demo_workspace
    return copy_demo_workspace(tmp_path)


def test_query_plan_is_bounded_by_tier(tmp_path: Path) -> None:
    plan = QueryPlanner(_workspace(tmp_path)).plan(tier="fast", limit=100, depth=9, enable_vector=True)
    assert plan.limit == 8
    assert plan.depth == 1
    assert plan.enable_vector is False


def test_invalidation_classifies_contract_paths(tmp_path: Path) -> None:
    plan = build_invalidation_plan(_workspace(tmp_path), ["demo/src/main/java/example/OrderDto.java"])
    assert plan["categories"] == ["dto_contract"]
    assert plan["rules"][0]["rule"] == "propagate_to_feign_mq_serialization"


def test_task_decision_and_evidence_gc_are_safe_by_default(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    task = create_task_space(workspace, title="架构决策")
    artifact = update_task_artifact(workspace, task["task_id"], "context", "证据" * (40 * 1024))
    decision = record_task_decision(workspace, task["task_id"], "索引", "使用 generation", "保证一致性", evidence_refs=[artifact["evidence"]["ref"]])
    gc = task_evidence_gc(workspace, task["task_id"])

    assert decision["recorded"] is True
    assert gc["apply"] is False
    assert gc["candidates"] == []


def test_watcher_schedules_coalesced_partial_reindex_and_generation_can_rollback(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    store = WorkspaceStore(workspace)
    reindex_workspace(load_workspace_config(workspace), store, parallel=False)
    first = index_control_status(store)["active_generation"]
    reindex_workspace(load_workspace_config(workspace), store, parallel=False)
    second = index_control_status(store)["active_generation"]

    rollback = rollback_generation(store)

    assert first != second
    assert rollback["rolled_back"] is True
    assert index_control_status(store)["active_generation"] == first
    queued = trigger_incremental_reindex(workspace, ["api/src/main/java/example/OrderDto.java"])
    assert queued["reindex_job"]["kind"] == "reindex"


def test_task_evidence_gc_keeps_evidence_referenced_only_by_decisions(tmp_path: Path) -> None:
    """decisions.jsonl 里的 evidence_refs 也算引用，GC 不得删除只被决策引用的证据。"""
    workspace = _workspace(tmp_path)
    task = create_task_space(workspace, title="决策专用证据")
    chunk = write_task_evidence_chunk(workspace, task["task_id"], "决策专用证据" * 500)
    decision = record_task_decision(
        workspace,
        task["task_id"],
        "索引",
        "使用 generation",
        "保证一致性",
        evidence_refs=[chunk["ref"]],
    )

    gc = task_evidence_gc(workspace, task["task_id"], apply=True)

    assert decision["recorded"] is True
    assert gc["candidates"] == []
    assert gc["removed"] == 0
    assert get_task_evidence_chunk(workspace, task["task_id"], chunk["ref"])["found"] is True
